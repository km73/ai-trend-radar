"""
热度算法 - 严格按提示词公式
Base = log10(view+1) + 0.5×log10(engagement+1)
DomainWeight = 2.0 顶级财经; 1.8 专业科技AI; 1.5 管理; 1.2 官方技术博客; 1.0 社交; 0.8 其他
RecencyDecay = exp(-HoursSincePublish / 72)
Score = (Base × RecencyDecay) + DomainWeight
Hot% = Score / maxScore × 100
Level: 80-100→5🔥 60-79→4🔴 40-59→3🟠 20-39→2🟡 0-19→1🟢
"""

import math
from datetime import datetime, timezone
from dateutil import parser as date_parser


def calc_hot_score(views: int, engagement: int, domain_weight: float,
                   time_published: str, now: datetime = None) -> float:
    """计算单条热度分"""
    if now is None:
        now = datetime.now(timezone.utc)

    # Base 分
    base = math.log10(views + 1) + 0.5 * math.log10(engagement + 1)

    # 近因衰减
    try:
        pub_dt = date_parser.isoparse(time_published)
        if pub_dt.tzinfo is None:
            pub_dt = pub_dt.replace(tzinfo=timezone.utc)
        hours_since = max(0, (now - pub_dt).total_seconds() / 3600)
    except Exception:
        hours_since = 240  # 默认按10天前
    recency_decay = math.exp(-hours_since / 72.0)

    # 最终分
    score = (base * recency_decay) + domain_weight
    return round(score, 3)


def calc_hot_percent(score: float, max_score: float) -> float:
    """计算热度百分比"""
    if max_score <= 0:
        return 0.0
    pct = (score / max_score) * 100
    return round(min(pct, 100.0), 1)


def calc_level(hot_percent: float) -> tuple:
    """映射级别: 返回 (level, emoji)"""
    if hot_percent >= 80:
        return (5, "🔥")
    elif hot_percent >= 60:
        return (4, "🔴")
    elif hot_percent >= 40:
        return (3, "🟠")
    elif hot_percent >= 20:
        return (2, "🟡")
    else:
        return (1, "🟢")


def score_all_articles(articles: list) -> list:
    """批量计算所有文章热度，并填充 hot_score/hot_percent/level 字段"""
    if not articles:
        return articles

    now = datetime.now(timezone.utc)
    scores = []
    for art in articles:
        s = calc_hot_score(
            art.get("views", 0),
            art.get("engagement", 0),
            art.get("domain_weight", 1.0),
            art.get("time_published"),
            now,
        )
        art["hot_score"] = s
        scores.append(s)

    max_score = max(scores) if scores else 1.0
    for art in articles:
        pct = calc_hot_percent(art["hot_score"], max_score)
        art["hot_percent"] = pct
        lvl, emoji = calc_level(pct)
        art["level"] = lvl
        art["level_emoji"] = emoji

    # 按热度分降序
    articles.sort(key=lambda x: x["hot_score"], reverse=True)
    return articles
