import json

import pytest

from metricguard.catalog.models import QueryRequest
from metricguard.catalog.builders import BUILDERS
from metricguard.policy.ast_rules import review

SEP = ("2026-09-01", "2026-09-30")


def ask(gw, question, **kwargs):
    return gw.ask(QueryRequest(question=question, start=SEP[0], end=SEP[1], **kwargs))


def test_strict_aov(gw):
    res = ask(gw, "9月客单价")
    assert res.ok, res.hint
    assert res.metric == "aov"
    assert res.value and res.value > 0
    assert res.ast_verdict == "pass"


def test_grouped_result_reports_overall_not_first_group(gw):
    grouped = ask(gw, "9月复购率按渠道")
    overall = ask(gw, "9月复购率")
    assert grouped.ok and overall.ok
    assert grouped.dimension == "register_channel"
    assert grouped.value == pytest.approx(overall.value, rel=1e-9)
    values = [row["v"] for row in grouped.rows]
    assert len(values) >= 3


def test_unregistered_metric_is_refused(gw):
    res = ask(gw, "预测明年会员增长")
    assert res.ok is False
    assert res.error_code == "metric_not_registered"


def test_dimension_fallback_is_explained(gw):
    res = ask(gw, "9月客单价按品类")
    assert res.ok
    assert res.metric == "aov"
    assert res.dimension is None
    assert "回退" in res.message


@pytest.mark.parametrize("metric", sorted(BUILDERS))
def test_every_metric_runs_in_strict_mode(gw, metric):
    from metricguard.catalog.loader import load_catalog
    from pathlib import Path

    specs = load_catalog(Path(__file__).resolve().parents[1] / "catalog" / "metrics")
    spec = specs[metric]
    sql, params = BUILDERS[metric](None, *SEP)
    verdict = review(sql)
    assert verdict.ok, (metric, verdict.findings)


def test_exploratory_valid_sql_runs(gw):
    sql = (
        "SELECT o.channel AS k, SUM(o.paid_amount) AS v "
        "FROM orders o JOIN members m ON o.member_id = m.member_id "
        "WHERE o.status <> 'refunded' AND CAST(o.order_time AS DATE) "
        "BETWEEN '2026-09-01' AND '2026-09-30' GROUP BY 1"
    )
    res = ask(gw, "看渠道GMV", mode="exploratory", sql=sql)
    assert res.ok, res.hint
    assert res.rows


def test_missing_limit_is_auto_repaired(gw):
    sql = (
        "SELECT o.order_id FROM orders o "
        "WHERE CAST(o.order_time AS DATE) BETWEEN '2026-09-01' AND '2026-09-30'"
    )
    res = ask(gw, "看看订单", mode="exploratory", sql=sql)
    assert res.ok, res.hint
    assert res.repaired == 1
    assert "LIMIT" in res.sql.upper()


def test_pii_is_blocked(gw):
    sql = (
        "SELECT member_id, phone FROM members "
        "WHERE CAST(register_date AS DATE) BETWEEN '2026-09-01' AND '2026-09-30'"
    )
    res = ask(gw, "导出手机号", mode="exploratory", sql=sql)
    assert res.ok is False
    assert "pii_column" in (res.error_code or "")


def test_delete_is_blocked(gw):
    res = ask(gw, "清理数据", mode="exploratory", sql="DELETE FROM orders")
    assert res.ok is False
    assert "not_read_only" in (res.error_code or "")


def test_exploratory_requires_sql(gw):
    res = ask(gw, "随便看看", mode="exploratory")
    assert res.ok is False
    assert res.error_code == "sql_required"


def test_audit_trail_is_written(gw, tmp_path):
    audit = tmp_path / "audit.jsonl"
    from metricguard.gateway import Gateway
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    g = Gateway(root / "catalog" / "metrics", root / "data" / "fixtures", audit)
    try:
        g.ask(QueryRequest(question="9月客单价", start=SEP[0], end=SEP[1]))
        g.ask(
            QueryRequest(
                question="导出手机号",
                mode="exploratory",
                sql="SELECT phone FROM members WHERE CAST(register_date AS DATE) BETWEEN '2026-09-01' AND '2026-09-30'",
            )
        )
    finally:
        g.close()

    lines = [json.loads(x) for x in audit.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    assert lines[0]["ok"] is True
    assert lines[1]["ok"] is False
    assert lines[1]["error_code"].startswith("policy_blocked")
    assert all("sql_hash" in row for row in lines)
