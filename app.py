"""
全球AI热点雷达 - FastAPI 主应用
单进程: 托管API + 静态前端 + 实时抓取 + 自动中文化翻译
"""

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Query, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import db
import scraper
import scorer
import translator
from seed_data import SEED_ARTICLES


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
