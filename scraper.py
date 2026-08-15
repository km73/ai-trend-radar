"""
多源抓取器 - 实时抓取AI热点
源: Hacker News API / Reddit JSON / RSS Feeds / GitHub Trending
失败优雅降级，每源独立超时
"""

import asyncio
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import httpx
import feedparser
from bs4 import BeautifulSoup

# 域名权重映射
DOMAIN_WEIGHTS = {
    # 顶级财经 2.0
    "reuters.com": 2.0, "bloomberg.com": 2.0, "wsj.com": 2.0, "ft.com": 2.0,
    "economist.com": 2.0, "apnews.com": 2.0, "cnbc.com": 2.0, "nikkei.com": 2.0,
    "barrons.com": 2.0, "finance.sina.com.cn": 2.0,
    # 专业科技AI 1.8
    "technologyreview.com": 1.8, "spectrum.ieee.org": 1.8, "venturebeat.com": 1.8,
    "arstechnica.com": 1.8, "techcrunch.com": 1.8, "theverge.com": 1.8,
    "wired.com": 1.8, "fastcompany.com": 1.8, "theinformation.com": 1.8,
    "semafor.com": 1.8, "syncedreview.com": 1.8, "jiqizhixin.com": 1.8,
    "qbitai.com": 1.8, "latepost.com": 1.8, "infoworld.com": 1.8,
    "businessinsider.com": 1.8, "36kr.com": 1.8,
    # 管理 1.5
    "hbr.org": 1.5, "mckinsey.com": 1.5, "sloanreview.mit.edu": 1.5,
    "gartner.com": 1.5, "deloitte.com": 1.5, "shrm.org": 1.5, "weforum.org": 1.5,
    "techjournal.org": 1.5, "stealthagents.com": 1.5, "iea.org": 1.5,
    "semianalysis.com": 1.5, "jishuzhan.net": 1.5,
    # 官方技术博客 1.2
    "openai.com": 1.2, "anthropic.com": 1.2, "blog.google": 1.2,
    "blogs.microsoft.com": 1.2, "aws.amazon.com": 1.2, "ai.meta.com": 1.2,
    "blogs.nvidia.com": 1.2, "huggingface.co": 1.2, "github.blog": 1.2,
    "deepmind.google": 1.2, "mistral.ai": 1.2, "x.ai": 1.2,
    "apple.com": 1.2, "huaweicloud.com": 1.5, "databricks.com": 1.8,
    "zhipu.ai": 1.8, "moonshot.ai": 1.8, "deepseek.com": 1.8, "cursor.com": 1.5,
    "figure.ai": 1.5, "sony.com": 1.5, "broadcom.com": 1.8,
    # 社交 1.0
    "reddit.com": 1.0, "news.ycombinator.com": 1.0, "x.com": 1.0,
    "twitter.com": 1.0, "linkedin.com": 1.0,
}

# AI 关键词（用于过滤）
AI_KEYWORDS = [
    "ai", "artificial intelligence", "machine learning", "deep learning",
    "llm", "large language model", "gpt", "chatgpt", "claude", "gemini",
    "openai", "anthropic", "deepmind", "neural", "transformer", "diffusion",
    "agent", "agentic", "rag", "mcp", "model", "inference", "training",
    "gpu", "nvidia", "huggingface", "generative", "foundation model",
    "大模型", "人工智能", "智能体", "生成式", "推理", "训练", "开源模型",
]


def clean_url(url: str) -> str:
    """去除跟踪参数"""
    if not url:
        return url
    try:
        parsed = urlparse(url)
        if not parsed.scheme:
            url = "https://" + url
            parsed = urlparse(url)
        q = parse_qs(parsed.query)
        # 移除跟踪参数
        track_keys = {"utm_source", "utm_medium", "utm_campaign", "utm_term",
                      "utm_content", "fbclid", "gclid", "mc_cid", "mc_eid"}
        clean_q = {k: v for k, v in q.items() if k.lower() not in track_keys}
        new_query = urlencode(clean_q, doseq=True)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path,
                           parsed.params, new_query, "")).rstrip("?")
    except Exception:
        return url


def get_domain_weight(url: str) -> float:
    """根据URL域名获取权重"""
    try:
        domain = urlparse(url).netloc.lower().replace("www.", "")
        for d, w in DOMAIN_WEIGHTS.items():
            if d in domain:
                return w
        return 0.8
    except Exception:
        return 0.8


def is_ai_related(text: str) -> bool:
    """判断文本是否与AI相关"""
    if not text:
        return False
    text_lower = text.lower()
    return any(kw in text_lower for kw in AI_KEYWORDS)


def infer_category(url: str, source: str, title: str) -> str:
    """推断内容类型"""
    url_lower = url.lower()
    src_lower = (source or "").lower()
    if any(x in url_lower for x in ["youtube.com", "tiktok.com", "vimeo.com"]):
        return "video"
    if any(x in src_lower for x in ["reddit", "hacker news", "twitter", "x.com", "linkedin"]):
        return "social"
    if any(x in url_lower for x in ["blog.", "/blog/", "/news/", "openai.com/news",
                                     "anthropic.com/news", "techcrunch.com", "theverge.com",
                                     "reuters.com", "bloomberg.com", "newsroom"]):
        if any(x in url_lower for x in ["review", "analysis", "opinion", "commentary",
                                         "hbr.org", "mckinsey", "gartner"]):
            return "commentary"
        return "news"
    return "news"


def infer_tags(title: str, summary: str = "") -> str:
    """推断主题标签"""
    text = (title + " " + (summary or "")).lower()
    tags = []
    if any(kw in text for kw in ["hr", "招聘", "人才", "recruit", "talent", "workforce",
                                  "员工", "人力资源", "shrm", "workday", "successfactors"]):
        tags.append("HR")
    if any(kw in text for kw in ["staffing", "rpo", "bpo", "adecco", "randstad",
                                  "manpower", "猎头", "外包", "人力资源服务"]):
        tags.append("HR服务")
    if not tags:
        tags.append("AI")
    else:
        tags.insert(0, "AI")
    return ";".join(tags)


# ============ Hacker News API ============
async def fetch_hackernews(client: httpx.AsyncClient, limit: int = 30) -> list:
    """抓取Hacker News AI相关故事"""
    articles = []
    try:
        # 使用Algolia API按时间窗口查询AI相关
        now_ts = int(time.time())
        week_ago = now_ts - 7 * 24 * 3600
        url = ("https://hn.algolia.com/api/v1/search_by_date"
               f"?query=AI%20artificial%20intelligence&tags=story"
               f"&numericFilters=created_at_i>{week_ago}&hitsPerPage={limit}")
        resp = await client.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        for hit in data.get("hits", []):
            title = hit.get("title", "")
            story_url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            if not is_ai_related(title):
                continue
            created = hit.get("created_at_i")
            pub_time = datetime.fromtimestamp(created, tz=timezone.utc).isoformat() if created else None
            points = hit.get("points", 0) or 0
            comments = hit.get("num_comments", 0) or 0
            articles.append({
                "title": title,
                "url": clean_url(story_url),
                "time_published": pub_time,
                "source": "Hacker News",
                "category": "social",
                "tags": infer_tags(title),
                "keywords": "AI,Hacker News,HN,社区讨论",
                "summary": f"HN社区热议：{title[:80]}（Hacker News discussion: {points} points, {comments} comments）",
                "why_hot": f"HN社区AI相关讨论，{points}赞{comments}评论",
                "takeaway": "关注开发者社区对AI技术的真实反馈与讨论",
                "views": points * 100,
                "engagement": points + comments * 2,
                "domain_weight": get_domain_weight(story_url),
                "language": "en",
            })
    except Exception as e:
        print(f"[Scraper] HN抓取失败: {e}")
    return articles


# ============ Reddit JSON ============
async def fetch_reddit(client: httpx.AsyncClient, subreddit: str, limit: int = 15) -> list:
    """抓取Reddit子版块热门帖子"""
    articles = []
    headers = {"User-Agent": "GlobalAIRadar/1.0 (research bot)"}
    try:
        url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}"
        resp = await client.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            title = d.get("title", "")
            permalink = d.get("permalink", "")
            full_url = f"https://www.reddit.com{permalink}" if permalink else ""
            if not full_url:
                continue
            created = d.get("created_utc")
            pub_time = datetime.fromtimestamp(created, tz=timezone.utc).isoformat() if created else None
            score = d.get("score", 0) or 0
            comments = d.get("num_comments", 0) or 0
            articles.append({
                "title": f"{title}（Reddit r/{subreddit}）",
                "url": clean_url(full_url),
                "time_published": pub_time,
                "source": f"Reddit r/{subreddit}",
                "category": "social",
                "tags": infer_tags(title),
                "keywords": f"Reddit,r/{subreddit},AI,社区讨论",
                "summary": f"Reddit社区r/{subreddit}热议：{title[:80]}（Reddit r/{subreddit}: {score} upvotes, {comments} comments）",
                "why_hot": f"Reddit r/{subreddit}讨论，{score}赞{comments}评论",
                "takeaway": "关注AI社区对技术趋势的真实讨论与反馈",
                "views": score * 80,
                "engagement": score + comments,
                "domain_weight": 1.0,
                "language": "en",
            })
    except Exception as e:
        print(f"[Scraper] Reddit r/{subreddit}抓取失败: {e}")
    return articles


async def fetch_all_reddit(client: httpx.AsyncClient) -> list:
    """抓取多个AI相关子版块"""
    subs = ["MachineLearning", "artificial", "singularity", "LocalLLaMA", "OpenAI"]
    tasks = [fetch_reddit(client, s, 12) for s in subs]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    all_arts = []
    for r in results:
        if isinstance(r, list):
            all_arts.extend(r)
    return all_arts


# ============ RSS Feeds ============
RSS_FEEDS = [
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ("MIT Tech Review", "https://www.technologyreview.com/feed/"),
    ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/"),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
    ("OpenAI Blog", "https://openai.com/blog/rss.xml"),
    ("Anthropic News", "https://www.anthropic.com/news/rss.xml"),
    ("Google AI Blog", "https://blog.google/technology/ai/rss/"),
    ("Hugging Face Blog", "https://huggingface.co/blog/feed.xml"),
    ("NVIDIA Blog", "https://blogs.nvidia.com/feed/"),
    ("Synced 机器之心", "https://www.jiqizhixin.com/rss"),
    ("量子位", "https://www.qbitai.com/feed"),
]


def parse_feed_sync(feed_name: str, feed_url: str) -> list:
    """同步解析单个RSS feed（feedparser不支持async）"""
    articles = []
    try:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:15]:
            title = entry.get("title", "")
            link = entry.get("link", "")
            if not link or not title:
                continue
            pub = entry.get("published_parsed") or entry.get("updated_parsed")
            if pub:
                pub_time = datetime(*pub[:6], tzinfo=timezone.utc).isoformat()
            else:
                pub_time = datetime.now(timezone.utc).isoformat()
            summary_raw = entry.get("summary", "") or entry.get("description", "")
            # 清理HTML
            if summary_raw:
                soup = BeautifulSoup(summary_raw, "html.parser")
                summary_clean = soup.get_text()[:200]
            else:
                summary_clean = ""
            articles.append({
                "title": title,
                "url": clean_url(link),
                "time_published": pub_time,
                "source": feed_name,
                "category": "news",
                "tags": infer_tags(title, summary_clean),
                "keywords": f"RSS,{feed_name},AI",
                "summary": summary_clean[:120] if summary_clean else f"来自{feed_name}的最新AI资讯（Latest AI news from {feed_name}）",
                "why_hot": f"{feed_name}最新发布，权威AI媒体跟踪",
                "takeaway": "关注权威AI媒体最新动态，把握技术趋势",
                "views": 5000,
                "engagement": 100,
                "domain_weight": get_domain_weight(link),
                "language": "zh" if any(c > "\u4e00" for c in title) else "en",
            })
    except Exception as e:
        print(f"[Scraper] RSS {feed_name} 解析失败: {e}")
    return articles


async def fetch_rss_feeds(client: httpx.AsyncClient) -> list:
    """异步抓取所有RSS feed（先用httpx获取内容，再feedparser解析）"""
    all_articles = []
    for name, url in RSS_FEEDS:
        try:
            resp = await client.get(url, timeout=15, follow_redirects=True)
            if resp.status_code == 200:
                # feedparser可解析原始内容
                import io
                feed = feedparser.parse(resp.content)
                for entry in feed.entries[:12]:
                    title = entry.get("title", "")
                    link = entry.get("link", "")
                    if not link or not title:
                        continue
                    pub = entry.get("published_parsed") or entry.get("updated_parsed")
                    if pub:
                        pub_time = datetime(*pub[:6], tzinfo=timezone.utc).isoformat()
                    else:
                        pub_time = datetime.now(timezone.utc).isoformat()
                    summary_raw = entry.get("summary", "") or entry.get("description", "")
                    if summary_raw:
                        soup = BeautifulSoup(summary_raw, "html.parser")
                        summary_clean = soup.get_text()[:200]
                    else:
                        summary_clean = ""
                    all_articles.append({
                        "title": title,
                        "url": clean_url(link),
                        "time_published": pub_time,
                        "source": name,
                        "category": "news",
                        "tags": infer_tags(title, summary_clean),
                        "keywords": f"RSS,{name},AI",
                        "summary": summary_clean[:120] if summary_clean else f"来自{name}的最新AI资讯（Latest AI news from {name}）",
                        "why_hot": f"{name}最新发布，权威AI媒体跟踪",
                        "takeaway": "关注权威AI媒体最新动态，把握技术趋势",
                        "views": 5000,
                        "engagement": 100,
                        "domain_weight": get_domain_weight(link),
                        "language": "zh" if any(ord(c) > 0x4e00 for c in title) else "en",
                    })
        except Exception as e:
            print(f"[Scraper] RSS {name} 抓取失败: {e}")
            continue
    return all_articles


# ============ GitHub Trending ============
async def fetch_github_trending(client: httpx.AsyncClient) -> list:
    """抓取GitHub Trending AI相关仓库"""
    articles = []
    try:
        resp = await client.get("https://github.com/trending?since=daily", timeout=15)
        if resp.status_code != 200:
            return articles
        soup = BeautifulSoup(resp.text, "html.parser")
        repos = soup.select("article.Box-row")[:20]
        for repo in repos:
            try:
                name_el = repo.select_one("h2 a")
                if not name_el:
                    continue
                repo_name = name_el.text.strip().replace("\n", "").replace(" ", "")
                repo_url = "https://github.com" + name_el.get("href", "")
                desc_el = repo.select_one("p")
                desc = desc_el.text.strip() if desc_el else ""
                # 检查AI相关
                if not is_ai_related(repo_name + " " + desc):
                    continue
                stars_el = repo.select("a.Link.Link--muted.d-inline-block.mr-3")
                stars = stars_el[0].text.strip() if stars_el else "0"
                articles.append({
                    "title": f"GitHub热门AI仓库：{repo_name} - {desc[:50]}",
                    "url": repo_url,
                    "time_published": datetime.now(timezone.utc).isoformat(),
                    "source": "GitHub Trending",
                    "category": "social",
                    "tags": infer_tags(repo_name + " " + desc),
                    "keywords": f"GitHub,开源 open-source,{repo_name},AI仓库",
                    "summary": f"GitHub Trending热门AI仓库：{repo_name}，{desc[:80]}（GitHub trending AI repo: {repo_name}）",
                    "why_hot": f"GitHub Trending每日热门，{stars} stars",
                    "takeaway": "关注开源AI项目动态，评估技术选型与社区活跃度",
                    "views": 8000,
                    "engagement": 200,
                    "domain_weight": 1.2,
                    "language": "en",
                })
            except Exception:
                continue
    except Exception as e:
        print(f"[Scraper] GitHub Trending抓取失败: {e}")
    return articles


# ============ 主抓取函数 ============
async def fetch_all_sources() -> dict:
    """并行抓取所有源，返回统计"""
    print("[Scraper] 开始并行抓取所有数据源...")
    start = time.time()

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; GlobalAIRadar/1.0; +https://ai-radar.local)"
    }
    timeout = httpx.Timeout(20.0, connect=10.0)

    async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True) as client:
        tasks = {
            "hackernews": fetch_hackernews(client, 30),
            "reddit": fetch_all_reddit(client),
            "rss": fetch_rss_feeds(client),
            "github": fetch_github_trending(client),
        }
        results = {}
        for name, task in tasks.items():
            try:
                results[name] = await task
            except Exception as e:
                print(f"[Scraper] {name} 整体失败: {e}")
                results[name] = []

    all_articles = []
    source_stats = {}
    for name, arts in results.items():
        source_stats[name] = len(arts)
        all_articles.extend(arts)

    # URL去重
    seen_urls = set()
    deduped = []
    for art in all_articles:
        u = art["url"]
        if u and u not in seen_urls:
            seen_urls.add(u)
            deduped.append(art)

    elapsed = time.time() - start
    print(f"[Scraper] 抓取完成: {len(deduped)}条 (去重后), 耗时{elapsed:.1f}s")
    print(f"[Scraper] 源统计: {source_stats}")

    return {
        "articles": deduped,
        "source_stats": source_stats,
        "elapsed_seconds": round(elapsed, 1),
        "total_fetched": len(all_articles),
        "after_dedup": len(deduped),
    }
