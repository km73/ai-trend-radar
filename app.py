"""
全球AI热点雷达 - FastAPI 主应用
单进程: 托管API + 静态前端 + 实时抓取 + 自动中文化翻译
"""

import asyncio
import hashlib
import hmac
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Query, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

import db
import scraper
import scorer
import translator
from seed_data import SEED_ARTICLES


# ===================================================================
# 门禁(Gate): 访问站点需输入密码 "Anson2026"
# 实现: 中间件校验签名 Cookie；未登录返回登录页；
#       /api/health 与 /api/login 对公网健康检查和登录放开。
# ===================================================================
GATE_PASSWORD = os.environ.get("GATE_PASSWORD", "Anson2026")
GATE_SECRET = os.environ.get("GATE_SECRET", "ai-radar-gate-secret-2026")
AUTH_COOKIE = "radar_auth"


def _make_token() -> str:
    return hmac.new(GATE_SECRET.encode(), b"authed", hashlib.sha256).hexdigest()


def _verify_token(tok: str) -> bool:
    return hmac.compare_digest(tok or "", _make_token())


LOGIN_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>全球AI热点雷达 · 访问验证</title>
<style>
  :root{--bg:#0d0f12;--surface:#15181d;--fg:#f2f4f7;--muted:#8b93a1;--accent:#39ff14;--line:#262b33}
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
    background:radial-gradient(1200px 600px at 50% -10%,#16241a 0%,var(--bg) 60%);
    font-family:'Archivo',system-ui,'PingFang SC','Microsoft YaHei',sans-serif;color:var(--fg)}
  .card{background:var(--surface);border:1px solid var(--line);border-radius:20px;
    padding:44px 40px;width:min(92vw,400px);box-shadow:0 20px 60px rgba(0,0,0,.5)}
  h1{font-size:34px;font-weight:800;letter-spacing:-.02em;margin:0 0 6px}
  .sub{color:var(--muted);font-size:13px;letter-spacing:.18em;text-transform:uppercase;margin-bottom:28px}
  label{display:block;font-size:13px;color:var(--muted);margin-bottom:8px}
  input{width:100%;padding:14px 16px;font-size:16px;border-radius:12px;border:1px solid var(--line);
    background:#0f1216;color:var(--fg);outline:none}
  input:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(57,255,20,.15)}
  button{margin-top:18px;width:100%;padding:14px;border:0;border-radius:12px;cursor:pointer;
    background:var(--accent);color:#06210a;font-weight:800;font-size:15px;letter-spacing:.04em;
    transition:transform .12s ease,filter .12s ease}
  button:hover{filter:brightness(1.08)}
  button:active{transform:translateY(1px)}
  .err{color:#ff6b6b;font-size:13px;min-height:18px;margin-top:12px}
</style></head>
<body><div class="card">
  <h1>全球AI热点雷达</h1>
  <div class="sub">ACCESS GATE · 访问验证</div>
  <label for="pw">请输入访问密码</label>
  <input id="pw" type="password" autocomplete="current-password" placeholder="密码" autofocus>
  <button id="btn">进入</button>
  <div class="err" id="err"></div>
</div>
<script>
  const pw=document.getElementById('pw'),btn=document.getElementById('btn'),err=document.getElementById('err');
  async function login(){
    err.textContent='';
    const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({password:pw.value})});
    if(r.ok){location.href='/';}
    else{const d=await r.json().catch(()=>({}));err.textContent=d.detail||d.error||'密码错误';}
  }
  btn.onclick=login;
  pw.addEventListener('keydown',e=>{if(e.key==='Enter')login();});
</script>
</body></html>"""


class GateMiddleware(BaseHTTPMiddleware):
    """未登录访问受保护资源时: API 返回 401, 页面返回登录页。"""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # 公开路径: 健康检查、登录/登出、静态资源、favicon
        if (path.startswith("/static") or path in ("/api/health", "/api/login", "/api/logout")
                or path == "/favicon.ico"):
            return await call_next(request)
        # 已登录放行
        if _verify_token(request.cookies.get(AUTH_COOKIE)):
            return await call_next(request)
        # 未登录
        if path.startswith("/api/"):
            return JSONResponse({"error": "unauthorized", "message": "需要访问密码"},
                                status_code=401)
        return HTMLResponse(LOGIN_HTML)


async def _translate_new_only(articles: list) -> int:
    """
    仅翻译 DB 中尚不存在的新文章，已存在的保留旧翻译。
    返回实际翻译篇数。
    """
    if not articles:
        return 0
    all_urls = [a.get("url") for a in articles if a.get("url")]
    existing = db.existing_urls(all_urls)
    need = [a for a in articles if a.get("url") not in existing]
    if not need:
        return 0

    print(f"[App] 检测到 {len(need)} 篇新文章，开始自动翻译为中文...")
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        def progress(done, total):
            if done % 6 == 0 or done == total:
                print(f"[App] 翻译进度 {done}/{total}")
        count = await translator.translate_articles(need, client=client,
                                                     on_progress=progress)
    print(f"[App] 翻译完成: {count} 篇")
    return count


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期: 启动时初始化DB、加载种子、加载已译URL缓存、后台抓取"""
    print("[App] 初始化数据库...")
    db.init_db()

    # 加载种子数据兜底（确保始终有内容）
    if db.count_all() == 0:
        print("[App] 数据库为空，加载种子数据...")
        scored = scorer.score_all_articles([dict(a) for a in SEED_ARTICLES])
        count = db.bulk_upsert(scored)
        print(f"[App] 种子数据加载: {count} 条")
        db.set_meta("last_refresh", datetime.now(timezone.utc).isoformat())

    # 预热翻译缓存：把已译 URL 灌入 translator，避免重复翻译
    for url in db.load_translated_urls():
        translator.mark_done(url)
    print(f"[App] 已加载 {len(db.load_translated_urls())} 条已译URL缓存")

    # 后台触发：先回填历史英文文章翻译，再实时抓取
    asyncio.create_task(background_refresh(initial_backfill=True))

    yield
    print("[App] 关闭中...")


async def background_refresh(initial_backfill: bool = False):
    """后台异步抓取 + 翻译，不阻塞启动"""
    try:
        await asyncio.sleep(2)  # 等服务先起来

        # 启动时先回填历史未翻译文章
        if initial_backfill:
            await backfill_translations()

        result = await scraper.fetch_all_sources()
        if result["articles"]:
            scored = scorer.score_all_articles(result["articles"])
            # 仅翻译新增（DB 不存在的）文章
            await _translate_new_only(scored)
            db.bulk_upsert(scored)
            db.set_meta("last_refresh", datetime.now(timezone.utc).isoformat())
            print(f"[App] 后台抓取完成: 处理 {len(scored)} 条")
    except Exception as e:
        print(f"[App] 后台抓取失败: {e}")


async def backfill_translations() -> int:
    """回填 DB 中历史英文文章的翻译"""
    try:
        pending = db.untranslated_articles()
        if not pending:
            print("[App] 无需回填翻译（全部已中文化）")
            return 0
        print(f"[App] 回填历史翻译: {len(pending)} 篇待译...")
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            count = await translator.translate_articles(pending, client=client)
        # 逐条写回
        written = 0
        for art in pending:
            ok = db.update_translation(
                art["id"], art.get("title", ""), art.get("summary", ""),
                art.get("why_hot", ""), art.get("takeaway", ""),
                art.get("original_title"), art.get("original_summary"),
            )
            if ok:
                written += 1
        print(f"[App] 回填写回: {written} 篇")
        return written
    except Exception as e:
        print(f"[App] 回填翻译失败: {e}")
        return 0


app = FastAPI(title="全球AI热点雷达", lifespan=lifespan)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

# 门禁中间件(必须在路由注册之后、请求处理之前挂载)
app.add_middleware(GateMiddleware)


@app.post("/api/login")
async def api_login(request: Request):
    """校验访问密码，成功则下发签名 Cookie。"""
    try:
        body = await request.json()
        pw = (body or {}).get("password", "")
    except Exception:
        pw = ""
    if not hmac.compare_digest(pw, GATE_PASSWORD):
        return JSONResponse({"error": "invalid_password", "message": "密码错误"},
                            status_code=401)
    resp = JSONResponse({"ok": True})
    resp.set_cookie(
        AUTH_COOKIE, _make_token(),
        httponly=True, samesite="lax",
        secure=os.environ.get("RENDER") is not None,
        max_age=60 * 60 * 24 * 30,  # 30 天
        path="/",
    )
    return resp


@app.post("/api/logout")
async def api_logout():
    """清除访问 Cookie。"""
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(AUTH_COOKIE, path="/")
    return resp


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """前端首页"""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/articles")
async def api_articles(
    category: str = Query("all", description="内容类型: news/commentary/social/video/all"),
    tag: str = Query("all", description="主题标签: AI/HR/HR服务/all"),
    q: str = Query("", description="搜索关键词（中英文均可）"),
    sort: str = Query("hot", description="排序: hot/time/views"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """获取文章列表，支持过滤/搜索/排序。英文内容已自动翻译为中文，原文保留在 original_title/original_summary。"""
    articles = db.query_articles(category=category, tag=tag, q=q or None,
                                  sort=sort, limit=limit, offset=offset)
    return {
        "total": len(articles),
        "category": category,
        "tag": tag,
        "q": q,
        "sort": sort,
        "articles": articles,
    }


@app.get("/api/articles/{article_id}")
async def api_article_detail(article_id: int):
    """获取单条文章详情（含原文）"""
    art = db.get_article_by_id(article_id)
    if not art:
        return JSONResponse({"error": "not found"}, status_code=404)
    return art


@app.get("/api/stats")
async def api_stats():
    """统计概览（含已翻译篇数）"""
    return db.get_stats()


@app.post("/api/refresh")
async def api_refresh(background_tasks: BackgroundTasks):
    """
    手动触发抓取刷新。
    新抓取的英文文章自动翻译为中文；已存在文章保留历史翻译，仅更新热度指标。
    """
    result = await scraper.fetch_all_sources()
    translated_count = 0
    if result["articles"]:
        scored = scorer.score_all_articles(result["articles"])
        translated_count = await _translate_new_only(scored)
        db.bulk_upsert(scored)
        db.set_meta("last_refresh", datetime.now(timezone.utc).isoformat())

    total = db.count_all()
    stats = db.get_stats()
    return {
        "status": "ok",
        "new_articles": result["after_dedup"],
        "translated": translated_count,
        "total_now": total,
        "translated_total": stats.get("translated", 0),
        "elapsed_seconds": result["elapsed_seconds"],
        "source_stats": result["source_stats"],
        "last_refresh": stats.get("last_refresh"),
    }


@app.post("/api/translate")
async def api_translate(background_tasks: BackgroundTasks):
    """手动触发历史英文文章回填翻译（后台执行）"""
    pending = db.untranslated_articles()
    if not pending:
        return {"status": "ok", "message": "无待翻译文章", "pending": 0}
    background_tasks.add_task(backfill_translations)
    return {"status": "started", "pending": len(pending),
            "message": f"后台开始翻译 {len(pending)} 篇历史英文文章"}


@app.get("/api/health")
async def health():
    stats = db.get_stats()
    return {
        "status": "ok",
        "total_articles": db.count_all(),
        "translated": stats.get("translated", 0),
    }


if __name__ == "__main__":
    import uvicorn
    # Render 通过环境变量 PORT 提供端口；本地默认 8787
    port = int(os.environ.get("PORT", 8787))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
