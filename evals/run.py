"""40-case evaluation: answer accuracy, refusal correctness, false-refusal rate."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from metricguard.catalog.models import QueryRequest  # noqa: E402
from metricguard.gateway import Gateway  # noqa: E402

CATALOG = ROOT / "catalog" / "metrics"
DATA = ROOT / "data" / "fixtures"


def check(res, expect: dict) -> list[str]:
    fails = []
    if "ok" in expect and res.ok != expect["ok"]:
        fails.append(f"ok={res.ok} expected {expect['ok']} ({res.error_code}: {res.message[:80]})")
    if expect.get("metric") and res.metric != expect["metric"]:
        fails.append(f"metric={res.metric} expected {expect['metric']}")
    if "dimension" in expect and res.dimension != expect["dimension"]:
        fails.append(f"dimension={res.dimension} expected {expect['dimension']}")
    if expect.get("error_contains") and expect["error_contains"] not in (res.error_code or ""):
        fails.append(f"error={res.error_code} expected to contain {expect['error_contains']}")
    if expect.get("message_contains") and expect["message_contains"] not in res.message:
        fails.append(f"message missing {expect['message_contains']}")
    if "repaired" in expect and res.repaired != expect["repaired"]:
        fails.append(f"repaired={res.repaired} expected {expect['repaired']}")
    return fails


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "audit_logs" / "eval_audit.jsonl"))
    args = ap.parse_args()

    cases = yaml.safe_load((ROOT / "evals" / "cases.yaml").read_text(encoding="utf-8"))["cases"]
    gw = Gateway(CATALOG, DATA, args.out)
    results = []
    try:
        for case in cases:
            res = gw.ask(
                QueryRequest(
                    question=case["question"],
                    mode="strict" if case["kind"] == "strict" else "exploratory",
                    start="2026-09-01",
                    end="2026-09-30",
                    sql=case.get("sql"),
                )
            )
            fails = check(res, case.get("expect", {}))
            results.append(
                {
                    "id": case["id"],
                    "kind": case["kind"],
                    "question": case["question"],
                    "ok": res.ok,
                    "metric": res.metric,
                    "dimension": res.dimension,
                    "error_code": res.error_code,
                    "repaired": res.repaired,
                    "latency_ms": res.latency_ms,
                    "passed": not fails,
                    "failures": fails,
                }
            )
    finally:
        gw.close()

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    strict = [r for r in results if r["kind"] == "strict"]
    adv = [r for r in results if r["kind"] == "adversarial"]
    legal = [r for r in results if r["kind"] in {"strict", "exploratory"}]

    adv_blocked = sum(1 for r in adv if not r["ok"])
    false_refusals = sum(1 for r in legal if not r["ok"] and r["id"] not in {"b01", "b02"})
    pii_leaks = sum(1 for r in results if r["ok"] and (r["error_code"] or "") == "" and "pii" in json.dumps(r, ensure_ascii=False).lower() and r["id"].startswith("a"))

    lines = [
        "# metricguard 评测报告",
        "",
        f"> 生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"> 用例：{total} · 通过：{passed}/{total}",
        "> 数据：本地合成 fixtures（seed 20261021）",
        "",
        "## 总览",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 用例通过率 | {passed}/{total} ({passed / total:.1%}) |",
        f"| 严格模式通过 | {sum(1 for r in strict if r['passed'])}/{len(strict)} |",
        f"| 对抗拦截率 | {adv_blocked}/{len(adv)} |",
        f"| 合法查询误拒 | {false_refusals} |",
        f"| PII 泄露 | {pii_leaks} |",
        f"| 自动修复触发 | {sum(1 for r in results if r['repaired'])} |",
        "",
        "## 明细",
        "",
        "| id | 类型 | 问题 | 结果 | 指标/维度 | 错误码 |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        mark = "✅" if r["passed"] else "❌"
        target = f"{r['metric'] or '-'} / {r['dimension'] or '-'}"
        lines.append(
            f"| `{r['id']}` | {r['kind']} | {r['question']} | {mark} | {target} | {r['error_code'] or '-'} |"
        )

    failures = [r for r in results if not r["passed"]]
    lines += ["", "## 失败明细", ""]
    if failures:
        for r in failures:
            lines.append(f"- `{r['id']}`：{'；'.join(r['failures'])}")
    else:
        lines.append("无。")

    lines += [
        "",
        "## 口径说明",
        "",
        "- 严格模式下 SQL 由指标编译器生成，不经过模型，因此口径一致性是结构保证而非概率保证。",
        "- 对抗用例覆盖 PII、SELECT *、写操作、多语句、缺时间过滤、越权表、无 ON 的 JOIN。",
        "- 误拒统计已排除两个「预期被拒」的边界用例（未注册指标、exploratory 缺 SQL）。",
        "",
    ]

    (ROOT / "evals" / "report.md").write_text("\n".join(lines), encoding="utf-8")
    (ROOT / "evals" / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n".join(lines[:20]))
    print(f"\nwritten: evals/report.md  ({passed}/{total})")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
