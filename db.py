"""
SQLite 数据库层 - 初始化 + CRUD + 原文存储/翻译持久化
"""

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

# 数据库文件放在项目目录内（Render 等平台的工作目录非 /workspace）
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_radar.db")
_lock = threading.Lock()


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _column_exists(conn, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def init_db():
    """初始化数据库表（含增量迁移：新增原文列）"""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                url TEXT UNIQUE NOT NULL,
                time_published TEXT,
                source TEXT,
                category TEXT,
                tags TEXT,
                keywords TEXT,
                summary TEXT,
                why_hot TEXT,
                takeaway TEXT,
                views INTEGER DEFAULT 0,
                engagement INTEGER DEFAULT 0,
                domain_weight REAL DEFAULT 1.0,
                hot_score REAL DEFAULT 0,
                hot_percent REAL DEFAULT 0,
                level INTEGER DEFAULT 1,
                level_emoji TEXT DEFAULT '🟢',
                language TEXT DEFAULT 'zh',
                original_title TEXT,
                original_summary TEXT,
                fetched_at TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_category ON articles(category)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_hot ON articles(hot_score DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_time ON articles(time_published DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tags ON articles(tags)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_lang ON articles(language)")

        # 增量迁移：旧库补列
        for col, decl in [("original_title", "TEXT"),
                          ("original_summary", "TEXT")]:
            if not _column_exists(conn, "articles", col):
                print(f"[DB] 迁移：新增列 {col}")
                conn.execute(f"ALTER TABLE articles ADD COLUMN {col} {decl}")

        # 元数据表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)


def upsert_article(conn, art: dict) -> bool:
    """
    插入或更新单条文章（按 url 去重）。
    冲突策略（保护已翻译内容）:
      - 新增行: 全字段写入
      - 已存在行: 仅刷新指标（views/engagement/hot_score/level/fetched_at/time_published），
        保留 title/summary/original_*/why_hot/takeaway/source/category/tags/keywords/language，
        避免每次刷新覆盖已翻译的中文内容与原文。
    """
    try:
        conn.execute("""
            INSERT INTO articles
                (title, url, time_published, source, category, tags, keywords,
                 summary, why_hot, takeaway, views, engagement, domain_weight,
                 hot_score, hot_percent, level, level_emoji, language,
                 original_title, original_summary, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                views=excluded.views,
                engagement=excluded.engagement,
                domain_weight=excluded.domain_weight,
                hot_score=excluded.hot_score,
                hot_percent=excluded.hot_percent,
                level=excluded.level,
                level_emoji=excluded.level_emoji,
                time_published=COALESCE(articles.time_published, excluded.time_published),
                fetched_at=excluded.fetched_at
        """, (
            art["title"], art["url"], art.get("time_published"),
            art.get("source"), art.get("category"), art.get("tags"),
            art.get("keywords"), art.get("summary"), art.get("why_hot"),
            art.get("takeaway"), art.get("views", 0), art.get("engagement", 0),
            art.get("domain_weight", 1.0), art.get("hot_score", 0),
            art.get("hot_percent", 0), art.get("level", 1),
            art.get("level_emoji", "🟢"), art.get("language", "zh"),
            art.get("original_title"), art.get("original_summary"),
            art.get("fetched_at", datetime.now(timezone.utc).isoformat()),
        ))
        return True
    except Exception as e:
        print(f"[DB] upsert失败: {e}")
        return False


def bulk_upsert(articles: list) -> int:
    """批量插入，返回成功条数"""
    count = 0
    with _lock, get_db() as conn:
        for art in articles:
            if upsert_article(conn, art):
                count += 1
    return count


def existing_urls(urls: list) -> set:
    """返回 urls 中已存在于 DB 的子集（用于判断哪些需要翻译）"""
    if not urls:
        return set()
    with get_db() as conn:
        # 分批避免 SQL 占位符上限
        result = set()
        for i in range(0, len(urls), 500):
            chunk = urls[i:i + 500]
            placeholders = ",".join("?" * len(chunk))
            rows = conn.execute(
                f"SELECT url FROM articles WHERE url IN ({placeholders})", chunk
            ).fetchall()
            result.update(r["url"] for r in rows)
        return result


def untranslated_articles(limit: Optional[int] = None) -> list:
    """
    返回需要回填翻译的文章：
    original_title 为空 且 标题不以中文为主（含拉丁字母但中文占比低）。
    limit 用于限流时每轮限量重试。
    """
    def mostly_zh(text: str) -> bool:
        if not text:
            return True
        zh = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        effective = sum(1 for c in text if c.isalnum() or "\u4e00" <= c <= "\u9fff")
        if effective == 0:
            return True
        return zh / effective > 0.3

    sql = """
        SELECT * FROM articles
        WHERE original_title IS NULL
        ORDER BY hot_score DESC
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    with get_db() as conn:
        rows = conn.execute(sql).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            t = d.get("title") or ""
            if not mostly_zh(t):
                out.append(d)
        return out


def update_translation(article_id: int, title: str, summary: str,
                       why_hot: str, takeaway: str,
                       original_title: Optional[str],
                       original_summary: Optional[str]) -> bool:
    """回填单条翻译结果（按 id）"""
    with _lock, get_db() as conn:
        cur = conn.execute("""
            UPDATE articles SET
                title=?, summary=?, why_hot=?, takeaway=?,
                original_title=COALESCE(?, original_title),
                original_summary=COALESCE(?, original_summary),
                language='zh'
            WHERE id=?
        """, (title, summary, why_hot, takeaway,
              original_title, original_summary, article_id))
        return cur.rowcount > 0


def load_translated_urls() -> set:
    """加载已翻译（original_title 非空 或 language=zh 且无原文标记）的 URL，避免重复翻译"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT url FROM articles WHERE original_title IS NOT NULL "
            "OR language='zh'"
        ).fetchall()
        return {r["url"] for r in rows}


def query_articles(
    category: Optional[str] = None,
    tag: Optional[str] = None,
    q: Optional[str] = None,
    sort: str = "hot",
    limit: int = 200,
    offset: int = 0,
) -> list:
    """查询文章列表"""
    sql = "SELECT * FROM articles WHERE 1=1"
    params = []

    if category and category.lower() != "all":
        sql += " AND category = ?"
        params.append(category)

    if tag and tag.lower() != "all":
        sql += f" AND (tags LIKE ? OR tags = ?)"
        params.append(f"%{tag}%")
        params.append(tag)

    if q:
        sql += (" AND (title LIKE ? OR summary LIKE ? OR keywords LIKE ? "
                "OR source LIKE ? OR original_title LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like, like, like])

    if sort == "time":
        sql += " ORDER BY time_published DESC"
    elif sort == "views":
        sql += " ORDER BY views DESC"
    else:  # hot
        sql += " ORDER BY hot_score DESC"

    sql += " LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def get_article_by_id(article_id: int) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        return dict(row) if row else None


def get_stats() -> dict:
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        by_cat = conn.execute(
            "SELECT category, COUNT(*) as c FROM articles GROUP BY category"
        ).fetchall()
        by_tag = {}
        for r in conn.execute("SELECT tags FROM articles").fetchall():
            for t in (r["tags"] or "").split(";"):
                t = t.strip()
                if t:
                    by_tag[t] = by_tag.get(t, 0) + 1
        top = conn.execute(
            "SELECT title, hot_percent, level_emoji, source FROM articles ORDER BY hot_score DESC LIMIT 1"
        ).fetchone()
        last_refresh = conn.execute(
            "SELECT value FROM meta WHERE key='last_refresh'"
        ).fetchone()
        translated = conn.execute(
            "SELECT COUNT(*) FROM articles WHERE original_title IS NOT NULL"
        ).fetchone()[0]
        return {
            "total": total,
            "by_category": {r["category"]: r["c"] for r in by_cat},
            "by_tag": by_tag,
            "top_article": dict(top) if top else None,
            "last_refresh": last_refresh[0] if last_refresh else None,
            "translated": translated,
        }


def set_meta(key: str, value: str):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def count_all() -> int:
    with get_db() as conn:
        return conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]


def clear_all():
    with _lock, get_db() as conn:
        conn.execute("DELETE FROM articles")
