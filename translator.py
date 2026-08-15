"""
自动翻译模块 - 英文内容自动翻译为中文
主源: Google Translate 非官方端点 (无需API Key，短文本稳定)
备源: MyMemory API (免费5000词/天)
策略:
  - 仅翻译非中文为主的内容（已是中文的跳过，省配额）
  - 并发限流 (semaphore=6) + 内存缓存，避免重复翻译
  - 保留原文存入 original_title / original_summary，列表显示中文译述
  - 失败优雅降级：返回原文，不阻塞抓取流程
"""

import asyncio
import re
import time
from typing import Optional

import httpx

# 进程内翻译缓存 (text -> zh)
_CACHE: dict = {}
# 已翻译 URL 集合（跨次刷新避免重译）
_DONE_URLS: set = set()

# 并发限流：Google 非官方端点对短文本较宽容，6 并发 + 小延迟较稳
_SEMAPHORE = asyncio.Semaphore(6)

GOOGLE_URL = "https://translate.googleapis.com/translate_a/single"
MYMEMORY_URL = "https://api.mymemory.translated.net/get"


def is_mostly_chinese(text: str) -> bool:
    """判断文本是否已以中文为主（中文字符占比 > 30% 即认为无需翻译）"""
    if not text:
        return True
    zh = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    # 统计有效字符（剔除空白与标点）
    effective = sum(1 for c in text if c.isalnum() or "\u4e00" <= c <= "\u9fff")
    if effective == 0:
        return True
    return zh / effective > 0.3


def has_chinese(text: str) -> bool:
    if not text:
        return False
    return any("\u4e00" <= c <= "\u9fff" for c in text)


async def _translate_google(client: httpx.AsyncClient, text: str,
                            target: str = "zh-CN") -> Optional[str]:
    try:
        params = {"client": "gtx", "sl": "auto", "tl": target, "dt": "t", "q": text}
        resp = await client.get(GOOGLE_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        # data[0] = [[translated_seg, original_seg, ...], ...]
        parts = []
        for seg in data[0]:
            if seg and seg[0]:
                parts.append(seg[0])
        return "".join(parts).strip() or None
    except Exception as e:
        print(f"[Translator] Google 翻译失败: {e}")
        return None


async def _translate_mymemory(client: httpx.AsyncClient, text: str) -> Optional[str]:
    try:
        params = {"q": text, "langpair": "en|zh-CN"}
        resp = await client.get(MYMEMORY_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        t = data.get("responseData", {}).get("translatedText")
        # MyMemory 偶尔返回错误信息
        if t and "MYMEMORY WARNING" not in t.upper():
            return t.strip() or None
        return None
    except Exception as e:
        print(f"[Translator] MyMemory 翻译失败: {e}")
        return None


async def translate_text(client: httpx.AsyncClient, text: str,
                         target: str = "zh-CN") -> str:
    """翻译单段文本为中文。已是中文则原样返回。失败返回原文。"""
    if not text or not text.strip():
        return text
    if is_mostly_chinese(text):
        return text

    cache_key = text
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    async with _SEMAPHORE:
        # 主源 Google
        result = await _translate_google(client, text, target)
        # 备源 MyMemory
        if not result or not result.strip():
            await asyncio.sleep(0.15)
            result = await _translate_mymemory(client, text)
        # 都失败：返回原文
        if not result:
            result = text

    # 清理：Google 偶尔在中文末尾带多余空格
    result = re.sub(r"\s{2,}", " ", result).strip()
    _CACHE[cache_key] = result
    return result


async def translate_article(client: httpx.AsyncClient, art: dict) -> dict:
    """
    就地翻译单篇文章的 title / summary / why_hot / takeaway。
    - 保留原文到 original_title / original_summary
    - 已是中文的文章跳过
    - language 标记为 'zh'（译后统一中文）
    """
    url = art.get("url", "")
    if url in _DONE_URLS:
        return art

    title = art.get("title", "") or ""
    summary = art.get("summary", "") or ""
    why_hot = art.get("why_hot", "") or ""
    takeaway = art.get("takeaway", "") or ""

    # 若标题已基本是中文，整体跳过（种子数据等）
    if is_mostly_chinese(title) and is_mostly_chinese(summary):
        _DONE_URLS.add(url)
        return art

    # 保留原文（仅当原文非空且确有英文/非中文内容时）
    if not is_mostly_chinese(title):
        translated_title = await translate_text(client, title)
        # 仅当实际发生翻译（结果与原文不同）才记录原文，避免中文被误存为"原文"
        if translated_title and translated_title != title:
            art["original_title"] = title
            art["title"] = translated_title
    if summary and not is_mostly_chinese(summary):
        translated_summary = await translate_text(client, summary)
        if translated_summary and translated_summary != summary:
            art["original_summary"] = summary
            art["summary"] = translated_summary
    # why_hot / takeaway 多为模板中文+少量英文，整段翻译更稳妥
    if why_hot and not is_mostly_chinese(why_hot):
        t = await translate_text(client, why_hot)
        if t and t != why_hot:
            art["why_hot"] = t
    if takeaway and not is_mostly_chinese(takeaway):
        t = await translate_text(client, takeaway)
        if t and t != takeaway:
            art["takeaway"] = t

    art["language"] = "zh"
    _DONE_URLS.add(url)
    return art


async def translate_articles(articles: list,
                              client: Optional[httpx.AsyncClient] = None,
                              on_progress=None) -> int:
    """
    批量翻译文章列表（就地修改）。
    并发限流 + 失败降级。返回实际翻译（非跳过）的篇数。
    """
    if not articles:
        return 0

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=15, follow_redirects=True)
    try:
        # 仅统计需要翻译的
        need = [a for a in articles
                if not is_mostly_chinese((a.get("title") or ""))]
        done = 0
        total = len(need)

        # 分批并发：每批 6 条
        BATCH = 6
        for i in range(0, total, BATCH):
            batch = need[i:i + BATCH]
            await asyncio.gather(
                *(translate_article(client, a) for a in batch),
                return_exceptions=True,
            )
            done += len(batch)
            if on_progress:
                on_progress(done, total)
            # 批间小延迟，降低被限流概率
            await asyncio.sleep(0.1)

        return done
    finally:
        if own_client:
            await client.aclose()


def mark_done(url: str):
    """标记某 URL 已翻译（用于从 DB 加载已译文章，避免重复翻译）"""
    if url:
        _DONE_URLS.add(url)
