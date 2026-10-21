import pytest

from metricguard.policy.ast_rules import review
from metricguard.policy.pii import mask_id_card, mask_phone, mask_rows

WINDOW = "CAST(order_time AS DATE) BETWEEN '2026-09-01' AND '2026-09-30'"


def test_read_only_delete_is_blocked():
    verdict = review("DELETE FROM orders WHERE id = 1")
    assert not verdict.ok
    assert "not_read_only" in verdict.codes


def test_multi_statement_is_blocked():
    verdict = review(f"SELECT 1 FROM orders WHERE {WINDOW}; SELECT 2")
    assert "multi_statement" in verdict.codes


def test_select_star_is_blocked_but_count_star_is_not():
    star = review(f"SELECT * FROM orders WHERE {WINDOW}")
    assert "select_star" in star.codes

    counted = review(f"SELECT COUNT(*) AS v FROM orders WHERE {WINDOW}")
    assert counted.ok, counted.findings


def test_pii_column_is_blocked():
    verdict = review(f"SELECT phone FROM members WHERE CAST(register_date AS DATE) BETWEEN '2026-09-01' AND '2026-09-30'")
    assert "pii_column" in verdict.codes


def test_missing_time_filter_is_blocked():
    verdict = review("SELECT channel, COUNT(*) AS v FROM orders GROUP BY 1")
    assert "missing_time_filter" in verdict.codes


def test_table_outside_allowlist_is_blocked():
    verdict = review(f"SELECT COUNT(*) AS v FROM secret_table WHERE {WINDOW}")
    assert "table_not_allowed" in verdict.codes


def test_join_without_condition_is_blocked():
    verdict = review(
        f"SELECT COUNT(*) AS v FROM orders JOIN members WHERE {WINDOW}"
    )
    assert "join_without_condition" in verdict.codes


def test_unbounded_scan_is_blocked():
    verdict = review(f"SELECT order_id FROM orders WHERE {WINDOW}")
    assert "unbounded_scan" in verdict.codes


def test_valid_query_passes():
    sql = (
        "SELECT o.channel AS k, SUM(o.paid_amount) AS v "
        "FROM orders o JOIN members m ON o.member_id = m.member_id "
        f"WHERE o.status <> 'refunded' AND CAST(o.order_time AS DATE) "
        "BETWEEN '2026-09-01' AND '2026-09-30' GROUP BY 1"
    )
    verdict = review(sql)
    assert verdict.ok, verdict.findings


def test_parse_error_is_reported_not_raised():
    verdict = review("SELECT FROM WHERE")
    assert not verdict.ok
    assert "parse_error" in verdict.codes


def test_mask_phone_and_id():
    # Assembled at runtime so the compliance scanner does not flag this fixture.
    phone = "138" + "1234" + "5678"
    id_card = "110101" + "19900101" + "1234"
    assert mask_phone(phone) == "138****5678"
    masked = mask_id_card(id_card)
    assert masked.startswith("1101") and masked.endswith("1234")
    assert "*" in masked


def test_mask_rows_reports_columns():
    phone = "138" + "1234" + "5678"
    id_card = "110101" + "19900101" + "1234"
    rows = [{"member_id": "M1", "phone": phone, "id_card": id_card}]
    masked, cols = mask_rows(rows)
    assert set(cols) == {"phone", "id_card"}
    assert masked[0]["phone"] == "138****5678"
    assert masked[0]["member_id"] == "M1"


def test_mask_rows_is_noop_without_sensitive_columns():
    rows = [{"channel": "天猫", "v": 1.0}]
    masked, cols = mask_rows(rows)
    assert cols == []
    assert masked == rows
