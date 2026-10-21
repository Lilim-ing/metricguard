"""Deterministic SQL compilers for every registered metric.

Strict mode never lets a model write SQL: the gateway compiles it here from the
metric contract. Exploratory mode does let a model write SQL, but the result has
to pass the same AST policy before it runs.

Convention: every builder emits `k` (dimension key) first when a dimension is
requested, then `v` (value). That keeps `GROUP BY 1` unambiguous.
"""

from __future__ import annotations

from typing import Any, Callable

DimMap = dict[str, str]

MEMBER_DIM: DimMap = {
    "register_channel": "m.register_channel",
    "member_level": "m.member_level",
    "city_tier": "m.city_tier",
    "age_band": "m.age_band",
}
ORDER_DIM: DimMap = {"channel": "o.channel", **MEMBER_DIM}
ITEM_DIM: DimMap = {"category": "i.category", "channel": "o.channel"}

PAID = "o.status <> 'refunded'"
WINDOW = "CAST(o.order_time AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)"


def _select(expr: str, dim: str | None, mapping: DimMap) -> tuple[str, str]:
    if not dim:
        return f"SELECT {expr} AS v", ""
    if dim not in mapping:
        raise ValueError(f"unsupported dimension {dim!r}; choose from {sorted(mapping)}")
    return f"SELECT {mapping[dim]} AS k, {expr} AS v", " GROUP BY 1 ORDER BY 2 DESC"


def _run(sql: str, params: list[Any]) -> tuple[str, list[Any]]:
    return " ".join(sql.split()), params


# ---------------------------------------------------------------- ratio metrics
def aov(dim: str | None, start: str, end: str) -> tuple[str, list[Any]]:
    head, grp = _select("SUM(o.paid_amount) / NULLIF(COUNT(*), 0)", dim, ORDER_DIM)
    sql = f"""
        {head}
        FROM orders o JOIN members m ON o.member_id = m.member_id
        WHERE {PAID} AND {WINDOW}
        {grp}
    """
    return _run(sql, [start, end])


def upt(dim: str | None, start: str, end: str) -> tuple[str, list[Any]]:
    head, grp = _select("SUM(i.qty) / NULLIF(COUNT(DISTINCT o.order_id), 0)", dim, ITEM_DIM)
    sql = f"""
        {head}
        FROM order_items i JOIN orders o ON i.order_id = o.order_id
        WHERE {PAID} AND {WINDOW}
        {grp}
    """
    return _run(sql, [start, end])


def return_rate(dim: str | None, start: str, end: str) -> tuple[str, list[Any]]:
    expr = "SUM(CASE WHEN i.is_returned = 1 THEN i.qty ELSE 0 END) / NULLIF(SUM(i.qty), 0)"
    head, grp = _select(expr, dim, ITEM_DIM)
    sql = f"""
        {head}
        FROM order_items i JOIN orders o ON i.order_id = o.order_id
        WHERE {WINDOW}
        {grp}
    """
    return _run(sql, [start, end])


def discount_rate(dim: str | None, start: str, end: str) -> tuple[str, list[Any]]:
    head, grp = _select(
        "SUM(o.discount_amount) / NULLIF(SUM(o.gross_amount), 0)", dim, ORDER_DIM
    )
    sql = f"""
        {head}
        FROM orders o JOIN members m ON o.member_id = m.member_id
        WHERE {PAID} AND {WINDOW}
        {grp}
    """
    return _run(sql, [start, end])


def member_gmv(dim: str | None, start: str, end: str) -> tuple[str, list[Any]]:
    head, grp = _select("SUM(o.paid_amount)", dim, ORDER_DIM)
    sql = f"""
        {head}
        FROM orders o JOIN members m ON o.member_id = m.member_id
        WHERE {PAID} AND {WINDOW}
        {grp}
    """
    return _run(sql, [start, end])


def refund_amount_rate(dim: str | None, start: str, end: str) -> tuple[str, list[Any]]:
    expr = "SUM(CASE WHEN o.status = 'refunded' THEN o.paid_amount ELSE 0 END) / NULLIF(SUM(o.paid_amount), 0)"
    head, grp = _select(expr, dim, {"channel": "o.channel"})
    sql = f"""
        {head}
        FROM orders o
        WHERE {WINDOW}
        {grp}
    """
    return _run(sql, [start, end])


def new_members(dim: str | None, start: str, end: str) -> tuple[str, list[Any]]:
    head, grp = _select("COUNT(DISTINCT m.member_id)", dim, MEMBER_DIM)
    sql = f"""
        {head}
        FROM members m
        WHERE CAST(m.register_date AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
        {grp}
    """
    return _run(sql, [start, end])


def orders_per_member(dim: str | None, start: str, end: str) -> tuple[str, list[Any]]:
    head, grp = _select("COUNT(*) / NULLIF(COUNT(DISTINCT o.member_id), 0)", dim, ORDER_DIM)
    sql = f"""
        {head}
        FROM orders o JOIN members m ON o.member_id = m.member_id
        WHERE {PAID} AND {WINDOW}
        {grp}
    """
    return _run(sql, [start, end])


# ------------------------------------------------------------- composite metrics
def repurchase_rate_90d(dim: str | None, start: str, end: str) -> tuple[str, list[Any]]:
    inner = f", {ORDER_DIM[dim]} AS k" if dim else ""
    grouped = "GROUP BY k, o.member_id" if dim else "GROUP BY o.member_id"
    outer = "SELECT k, " if dim else "SELECT "
    outer_grp = " GROUP BY 1 ORDER BY 2 DESC" if dim else ""
    sql = f"""
        {outer}AVG(CASE WHEN n >= 2 THEN 1.0 ELSE 0.0 END) AS v
        FROM (
          SELECT o.member_id, COUNT(*) AS n {inner}
          FROM orders o JOIN members m ON o.member_id = m.member_id
          WHERE {PAID}
            AND CAST(o.order_time AS DATE) BETWEEN CAST(? AS DATE) - INTERVAL 89 DAY AND CAST(? AS DATE)
          {grouped}
        ) t
        {outer_grp}
    """
    return _run(sql, [end, end])


def active_rate_30d(dim: str | None, start: str, end: str) -> tuple[str, list[Any]]:
    inner = f", {MEMBER_DIM[dim]} AS k" if dim else ""
    outer = "SELECT k, " if dim else "SELECT "
    outer_grp = " GROUP BY 1 ORDER BY 2 DESC" if dim else ""
    joined_cols = "b.member_id, b.k" if dim else "b.member_id"
    sql = f"""
        WITH base AS (
          SELECT m.member_id {inner} FROM members m
          WHERE CAST(m.register_date AS DATE) <= CAST(? AS DATE)
        ),
        act AS (
          SELECT DISTINCT member_id FROM orders
          WHERE status <> 'refunded'
            AND CAST(order_time AS DATE) BETWEEN CAST(? AS DATE) - INTERVAL 29 DAY AND CAST(? AS DATE)
          UNION
          SELECT DISTINCT member_id FROM behaviors
          WHERE CAST(event_time AS DATE) BETWEEN CAST(? AS DATE) - INTERVAL 29 DAY AND CAST(? AS DATE)
        ),
        joined AS (
          SELECT {joined_cols},
                 CASE WHEN a.member_id IS NULL THEN 0.0 ELSE 1.0 END AS hit
          FROM base b LEFT JOIN act a USING(member_id)
        )
        {outer}AVG(hit) AS v FROM joined {outer_grp}
    """
    return _run(sql, [end, end, end, end, end])


def churn_rate_180d(dim: str | None, start: str, end: str) -> tuple[str, list[Any]]:
    inner = f", {MEMBER_DIM[dim]} AS k" if dim else ""
    outer = "SELECT k, " if dim else "SELECT "
    outer_grp = " GROUP BY 1 ORDER BY 2 DESC" if dim else ""
    joined_cols = "b.member_id, b.k" if dim else "b.member_id"
    sql = f"""
        WITH base AS (
          SELECT m.member_id {inner} FROM members m
          WHERE CAST(m.register_date AS DATE) <= CAST(? AS DATE)
        ),
        lb AS (
          SELECT member_id, MAX(CAST(order_time AS DATE)) AS d
          FROM orders WHERE status <> 'refunded' GROUP BY member_id
        ),
        joined AS (SELECT {joined_cols}, lb.d FROM base b JOIN lb USING(member_id))
        {outer}AVG(CASE WHEN DATE_DIFF('day', d, CAST(? AS DATE)) >= 180 THEN 1.0 ELSE 0.0 END) AS v
        FROM joined {outer_grp}
    """
    return _run(sql, [start, end])


def repeat_gmv_share(dim: str | None, start: str, end: str) -> tuple[str, list[Any]]:
    inner = f", {MEMBER_DIM[dim]} AS k" if dim else ""
    grouped = "GROUP BY k, o.member_id" if dim else "GROUP BY o.member_id"
    outer = "SELECT k, " if dim else "SELECT "
    outer_grp = " GROUP BY 1 ORDER BY 2 DESC" if dim else ""
    sql = f"""
        WITH per AS (
          SELECT o.member_id, COUNT(*) AS n, SUM(o.paid_amount) AS gmv {inner}
          FROM orders o JOIN members m ON o.member_id = m.member_id
          WHERE {PAID} AND {WINDOW}
          {grouped}
        )
        {outer}SUM(CASE WHEN n >= 2 THEN gmv ELSE 0 END) / NULLIF(SUM(gmv), 0) AS v
        FROM per {outer_grp}
    """
    return _run(sql, [start, end])


BUILDERS: dict[str, Callable[[str | None, str, str], tuple[str, list[Any]]]] = {
    "aov": aov,
    "upt": upt,
    "return_rate": return_rate,
    "discount_rate": discount_rate,
    "member_gmv": member_gmv,
    "refund_amount_rate": refund_amount_rate,
    "new_members": new_members,
    "orders_per_member": orders_per_member,
    "repurchase_rate_90d": repurchase_rate_90d,
    "active_rate_30d": active_rate_30d,
    "churn_rate_180d": churn_rate_180d,
    "repeat_gmv_share": repeat_gmv_share,
}
