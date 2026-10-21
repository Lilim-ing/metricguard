"""AST policy engine.

Every SQL statement -- generated in strict mode or written by hand in
exploratory mode -- passes through this review before it is allowed to run.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

ALLOWED_TABLES = {
    "members",
    "orders",
    "order_items",
    "products",
    "behaviors",
    "campaigns",
    "campaign_assignments",
}

PII_COLUMNS = {"phone", "id_card", "address", "email", "real_name", "name"}
TIME_COLUMNS = {"order_time", "register_date", "event_time", "start_date", "end_date"}

FORBIDDEN_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Alter,
    exp.Create,
    exp.Command,
    exp.TruncateTable,
)


@dataclass
class Finding:
    code: str
    detail: str
    severity: str = "block"

    def as_dict(self) -> dict:
        return {"code": self.code, "detail": self.detail, "severity": self.severity}


@dataclass
class Review:
    ok: bool
    findings: list[Finding] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)

    @property
    def codes(self) -> list[str]:
        return [f.code for f in self.findings]

    def summary(self) -> str:
        return "pass" if self.ok else ",".join(self.codes)


def _is_time_column(node: exp.Expression) -> bool:
    return isinstance(node, exp.Column) and node.name.lower() in TIME_COLUMNS


def _time_columns_in(node: exp.Expression | None) -> bool:
    if node is None:
        return False
    if _is_time_column(node):
        return True
    return any(_is_time_column(col) for col in node.find_all(exp.Column))


def _has_time_filter(tree: exp.Expression) -> bool:
    for between in tree.find_all(exp.Between):
        if _time_columns_in(between.this):
            return True
    for cls in (exp.GTE, exp.LTE, exp.GT, exp.LT):
        for cmp in tree.find_all(cls):
            if _time_columns_in(cmp.this) or _time_columns_in(cmp.expression):
                return True
    return False


def _has_aggregate(tree: exp.Expression) -> bool:
    return any(True for _ in tree.find_all(exp.AggFunc))


def _has_limit(tree: exp.Expression) -> bool:
    return tree.args.get("limit") is not None


def review(
    sql: str,
    *,
    require_time_filter: bool = True,
    require_limit_or_aggregate: bool = True,
    allowed_tables: set[str] | None = None,
) -> Review:
    tables_allowed = allowed_tables or ALLOWED_TABLES
    findings: list[Finding] = []

    try:
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except Exception as exc:  # noqa: BLE001
        return Review(ok=False, findings=[Finding("parse_error", str(exc)[:200])])

    if len(statements) != 1:
        return Review(
            ok=False,
            findings=[Finding("multi_statement", f"expected 1 statement, got {len(statements)}")],
        )

    tree = statements[0]

    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            findings.append(Finding("not_read_only", type(node).__name__))
            break

    if not isinstance(tree, (exp.Select, exp.Union, exp.Subquery)):
        findings.append(Finding("not_read_only", f"top-level {type(tree).__name__}"))

    cte_names = {(cte.alias_or_name or "").lower() for cte in tree.find_all(exp.CTE)}
    tables: list[str] = []
    for table in tree.find_all(exp.Table):
        name = (table.name or "").lower()
        if not name or name in cte_names:
            continue
        tables.append(name)
        if name not in tables_allowed:
            findings.append(Finding("table_not_allowed", name))

    # Only a star in the SELECT list counts. COUNT(*) contains a Star node too,
    # and blocking that would reject every aggregate query.
    for select in tree.find_all(exp.Select):
        for projected in select.expressions:
            if isinstance(projected, exp.Star):
                findings.append(Finding("select_star", "禁止 SELECT *，必须显式列出字段"))
            elif isinstance(projected, exp.Column) and isinstance(projected.this, exp.Star):
                findings.append(Finding("select_star", f"禁止 {projected.sql(dialect='duckdb')}"))

    for column in tree.find_all(exp.Column):
        if column.name.lower() in PII_COLUMNS:
            findings.append(Finding("pii_column", f"列 {column.name} 属于敏感字段"))

    for join in tree.find_all(exp.Join):
        kind = (join.args.get("kind") or "").upper()
        if kind in {"CROSS", "OUTER"}:
            findings.append(Finding("cartesian_join", f"{kind} JOIN 被禁止"))
        elif join.args.get("on") is None and join.args.get("using") is None:
            findings.append(Finding("join_without_condition", "JOIN 必须带 ON/USING"))

    if require_time_filter and not _has_time_filter(tree):
        findings.append(
            Finding("missing_time_filter", "查询必须带时间过滤（order_time / register_date / event_time）")
        )

    if require_limit_or_aggregate and not (_has_limit(tree) or _has_aggregate(tree)):
        findings.append(Finding("unbounded_scan", "必须带 LIMIT 或聚合，避免全表拉取"))

    blocked = [f for f in findings if f.severity == "block"]
    return Review(ok=not blocked, findings=findings, tables=sorted(set(tables)))
