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
import os
import random
import re
import time
from typing import Optional

import httpx

# 进程内翻译缓存 (text -> zh)
_CACHE: dict = {}
# 已翻译 URL 集合（跨次刷新避免重译）
_DONE_URLS: set = set()

# 并发限流：Google 非官方端点对短文本较宽容，但仍会 429。
# 3 并发 + 批间退避，成功率显著高于 6 并发猛冲。
_SEMAPHORE = asyncio.Semaphore(3)

GOOGLE_URL = "https://translate.googleapis.com/translate_a/single"
MYMEMORY_URL = "https://api.mymemory.translated.net/get"

# 单次翻译的最大尝试轮数（每轮会依次试 Google -> MyMemory）
MAX_ATTEMPTS = int(os.environ.get("TRANSLATE_ATTEMPTS", "3"))

# 熔断器：某个源连续被限流时，冷却期间直接跳过，避免反复撞墙浪费时间。
# source -> 冷却截止时间戳(monotonic)
_source_cooldown: dict = {}
SOURCE_COOLDOWN_SEC = int(os.environ.get("TRANSLATE_COOLDOWN_SEC", "60"))


class TransientError(Exception):
    """可重试错误（限流/超时/5xx），不应把文章标记为"已处理"。"""


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
    params = {"client": "gtx", "sl": "auto", "tl": target, "dt": "t", "q": text}
    resp = await client.get(GOOGLE_URL, params=params, timeout=12)
    # 限流 / 服务端错误 -> 抛可重试异常，交给上层退避重试
    if resp.status_code == 429 or resp.status_code >= 500:
        raise TransientError(f"google {resp.status_code}")
    resp.raise_for_status()
    data = resp.json()
    # data[0] = [[translated_seg, original_seg, ...], ...]
    parts = []
    for seg in data[0]:
        if seg and seg[0]:
            parts.append(seg[0])
    return "".join(parts).strip() or None


async def _translate_mymemory(client: httpx.AsyncClient, text: str,
                              target: str = "zh-CN") -> Optional[str]:
    params = {"q": text, "langpair": "en|zh-CN"}
    resp = await client.get(MYMEMORY_URL, params=params, timeout=12)
    if resp.status_code == 429 or resp.status_code >= 500:
        raise TransientError(f"mymemory {resp.status_code}")
    resp.raise_for_status()
    data = resp.json()
    # MyMemory 配额耗尽时会在 responseDetails 里提示
    details = (data.get("responseDetails") or "").upper()
    if "LIMIT" in details or "QUOTA" in details:
        raise TransientError("mymemory quota")
    t = data.get("responseData", {}).get("translatedText")
    # MyMemory 偶尔返回错误信息
    if t and "MYMEMORY WARNING" not in t.upper():
        return t.strip() or None
    return None


def _source_open(name: str) -> bool:
    """判断源是否处于可用状态（未触发冷却）"""
    return time.monotonic() >= _source_cooldown.get(name, 0.0)


def _open_circuit(name: str):
    """源连续失败时打开熔断，冷却 SOURCE_COOLDOWN_SEC 秒"""
    _source_cooldown[name] = time.monotonic() + SOURCE_COOLDOWN_SEC


async def translate_text(client: httpx.AsyncClient, text: str,
                         target: str = "zh-CN") -> str:
    """
    翻译单段文本为中文。已是中文则原样返回。
    失败(限流/超时)时退避重试，全部轮次失败才返回原文。
    每个源独立熔断：被限流后冷却期内跳过，给限流窗口恢复时间。
    """
    if not text or not text.strip():
        return text
    if is_mostly_chinese(text):
        return text

    cache_key = text
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    result = None
    async with _SEMAPHORE:
        for attempt in range(MAX_ATTEMPTS):
            # 每轮依次尝试未熔断的源（主源 Google -> 备源 MyMemory）
            for name, fn in (("google", _translate_google),
                             ("mymemory", _translate_mymemory)):
                if not _source_open(name):
                    continue
                try:
                    r = await fn(client, text, target)
                    if r and r.strip():
                        result = r
                        break
                except TransientError as e:
                    print(f"[Translator] {name} 暂时不可用({e})，熔断 {SOURCE_COOLDOWN_SEC}s")
                    _open_circuit(name)
                except Exception as e:
                    print(f"[Translator] {name} 翻译异常: {e}")
            if result:
                break
            # 本轮全部失败 -> 指数退避 + 抖动，避免集体撞限流
            if attempt < MAX_ATTEMPTS - 1:
                wait = 0.6 * (2 ** attempt) + random.uniform(0, 0.5)
                await asyncio.sleep(wait)

    # 都失败：返回原文（调用方据此判断"未真正翻译"，允许后续重试）
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

    title_is_zh = is_mostly_chinese(title)

    # 若标题已基本是中文，整体跳过（种子数据等）
    if title_is_zh and is_mostly_chinese(summary):
        _DONE_URLS.add(url)
        return art

    # 保留原文（仅当原文非空且确有英文/非中文内容时）
    # ok 标记"标题是否已确认为中文"——标题是判定翻译成功的关键字段，
    # 只有标题到位才标记完成，否则留给后续周期重试（防止限流时永久漏译）
    ok = title_is_zh
    if not title_is_zh:
        translated_title = await translate_text(client, title)
        # 仅当实际发生翻译（结果与原文不同）才记录原文，避免中文被误存为"原文"
        if translated_title and translated_title != title:
            art["original_title"] = title
            art["title"] = translated_title
            ok = True
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
    if ok:
        _DONE_URLS.add(url)
    return art


async def translate_articles(articles: list,
                              client: Optional[httpx.AsyncClient] = None,
                              on_progress=None) -> int:
    """
    批量翻译文章列表（就地修改）。
    并发限流 + 失败降级 + 分批退避。
    返回**真正翻译成功**的篇数（含原本就是中文而跳过的）。
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
        total = len(need)

        # 分批并发：每批 3 条（配合 semaphore=3，降低触发 429 的概率）
        BATCH = 3
        succeeded = 0
        for i in range(0, total, BATCH):
            batch = need[i:i + BATCH]
            await asyncio.gather(
                *(translate_article(client, a) for a in batch),
                return_exceptions=True,
            )
            succeeded += sum(
                1 for a in batch
                if is_mostly_chinese(a.get("title") or "")
            )
            if on_progress:
                on_progress(min(i + BATCH, total), total)
            # 批间退避 + 抖动；每 10 批多歇一会，给限流窗口留出恢复时间
            if i + BATCH < total:
                if (i // BATCH) % 10 == 9:
                    await asyncio.sleep(2.0)
                else:
                    await asyncio.sleep(0.35 + random.uniform(0, 0.25))

        return succeeded
    finally:
        if own_client:
            await client.aclose()


def mark_done(url: str):
    """标记某 URL 已翻译（用于从 DB 加载已译文章，避免重复翻译）"""
    if url:
        _DONE_URLS.add(url)
