"""Reverse-check the compiled SQL against the declared definition.

This is a structural check on the aggregate set plus the mandatory refund
filter -- not a proof of SQL equivalence. Saying so explicitly is more useful
than pretending a parser can decide semantic equality.
"""

from __future__ import annotations

import re

from sqlglot import exp, parse_one

from ..catalog.models import MetricSpec

AGG_WORDS = ("sum", "count", "avg", "min", "max")


def declared_aggregates(spec: MetricSpec) -> set[str]:
    if spec.expected_aggregates:
        return {a.lower() for a in spec.expected_aggregates}
    text = f"{spec.numerator} {spec.denominator or ''}".lower()
    return {word for word in AGG_WORDS if re.search(rf"\b{word}\b", text)}


def found_aggregates(sql: str) -> set[str]:
    tree = parse_one(sql, read="duckdb")
    return {type(node).__name__.lower() for node in tree.find_all(exp.AggFunc)}


def verify(sql: str, spec: MetricSpec) -> list[str]:
    issues: list[str] = []
    declared = declared_aggregates(spec)
    found = found_aggregates(sql)

    missing = declared - found
    if missing:
        issues.append(f"口径核对：声明使用 {sorted(declared)}，SQL 缺少 {sorted(missing)}")

    definition = f"{spec.description} {spec.numerator} {spec.denominator or ''}".lower()
    if "refunded" in definition and "refunded" not in sql.lower():
        issues.append("口径核对：该指标要求剔除退款订单，但 SQL 中没有 refunded 过滤")

    return issues
