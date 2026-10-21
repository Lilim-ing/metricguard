"""Question -> (metric, dimension, window).

Deliberately simple and inspectable. When a question cannot be matched to a
registered metric, strict mode refuses instead of guessing -- that refusal is a
feature, not a limitation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

METRIC_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    # More specific phrases must come first: "复购GMV占比" also contains "复购".
    (("复购gmv", "复购贡献"), "repeat_gmv_share"),
    (("复购", "二次购买", "回购"), "repurchase_rate_90d"),
    (("活跃", "互动"), "active_rate_30d"),
    (("流失", "沉睡", "沉默"), "churn_rate_180d"),
    (("客单", "aov", "平均订单金额"), "aov"),
    (("连带", "件单", "每单件数"), "upt"),
    (("退货", "退货率"), "return_rate"),
    (("折扣", "折扣率"), "discount_rate"),
    (("新增", "拉新", "新会员"), "new_members"),
    (("gmv", "销售额", "成交额"), "member_gmv"),
    (("人均订单", "单量"), "orders_per_member"),
    (("退款金额", "退款率"), "refund_amount_rate"),
]

DIMENSION_KEYWORDS: list[tuple[tuple[str, ...], list[str]]] = [
    (("注册渠道",), ["register_channel"]),
    # "渠道" is ambiguous: order-level metrics cut by order channel, member-level
    # metrics can only cut by registration channel. Keep both candidates and let
    # the gateway pick the first one the metric actually supports.
    (("渠道",), ["channel", "register_channel"]),
    (("会员等级", "等级", "会员分层"), ["member_level"]),
    (("城市", "线级"), ["city_tier"]),
    (("年龄",), ["age_band"]),
    (("品类", "品类结构"), ["category"]),
]


@dataclass
class Match:
    metric: str | None
    dimension: str | None
    start: str
    end: str
    confidence: float
    reason: str
    dimensions: list[str] | None = None


def _month_window(year: int, month: int) -> tuple[str, str]:
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    last = date.fromordinal(nxt.toordinal() - 1)
    return date(year, month, 1).isoformat(), last.isoformat()


def extract_window(question: str, today: str) -> tuple[str, str, str]:
    m = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月", question)
    if m:
        start, end = _month_window(int(m.group(1)), int(m.group(2)))
        return start, end, f"{m.group(1)}-{int(m.group(2)):02d}"

    m = re.search(r"(?<!\d)(\d{1,2})\s*月", question)
    if m:
        year = date.fromisoformat(today).year
        month = int(m.group(1))
        if 1 <= month <= 12:
            start, end = _month_window(year, month)
            return start, end, f"{year}-{month:02d}"

    if "上个月" in question or "上月" in question:
        d = date.fromisoformat(today)
        year, month = (d.year - 1, 12) if d.month == 1 else (d.year, d.month - 1)
        start, end = _month_window(year, month)
        return start, end, f"{year}-{month:02d}"

    # default: the month containing `today`
    d = date.fromisoformat(today)
    start, end = _month_window(d.year, d.month)
    return start, end, f"{d.year}-{d.month:02d}"


def match(question: str, available: set[str], today: str = "2026-09-30") -> Match:
    text = question.lower()

    metric = None
    for keywords, name in METRIC_KEYWORDS:
        if any(k in text for k in keywords) and name in available:
            metric = name
            break

    candidates: list[str] = []
    for keywords, names in DIMENSION_KEYWORDS:
        if any(k in text for k in keywords):
            candidates.extend(n for n in names if n not in candidates)

    start, end, label = extract_window(question, today)
    if metric is None:
        return Match(None, None, start, end, 0.0, "未命中任何已注册指标", candidates)
    return Match(
        metric,
        candidates[0] if candidates else None,
        start,
        end,
        0.9,
        f"命中指标 {metric}，窗口 {label}",
        candidates,
    )
