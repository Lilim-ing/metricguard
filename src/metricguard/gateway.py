"""The gateway: question in, governed answer out.

Order of operations is deliberate:

    resolve -> compile -> AST review -> definition check -> execute -> mask -> audit

Nothing reaches the database before it has passed the policy engine, and nothing
reaches the caller before masking and auditing.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from pathlib import Path

from .audit.log import AuditLog
from .catalog.builders import BUILDERS
from .catalog.loader import CatalogError, load_catalog
from .catalog.models import QueryRequest, QueryResult
from .exec.engine import Engine
from .nl2sql.matcher import match
from .nl2sql.repair import auto_fix, classify
from .nl2sql.verifier import verify
from .policy.ast_rules import review
from .policy.pii import mask_rows


class Gateway:
    def __init__(
        self,
        catalog_dir: str | Path,
        data_dir: str | Path,
        audit_path: str | Path,
        max_rows: int = 5000,
        today: str = "2026-09-30",
    ) -> None:
        self.specs = load_catalog(catalog_dir)
        missing = set(self.specs) - set(BUILDERS)
        extra = set(BUILDERS) - set(self.specs)
        if missing or extra:
            raise CatalogError(
                f"catalog/builders mismatch: missing={sorted(missing)} extra={sorted(extra)}"
            )
        self.engine = Engine(data_dir, max_rows=max_rows)
        self.audit = AuditLog(audit_path)
        self.today = today

    # ------------------------------------------------------------------
    def ask(self, req: QueryRequest) -> QueryResult:
        started = time.perf_counter()
        rid = f"q-{uuid.uuid4().hex[:10]}"
        metric_name: str | None = None
        dim: str | None = None
        spec = None
        repaired = 0
        note = ""
        start, end = req.start, req.end

        # 1. resolve + compile
        if req.mode == "strict":
            m = match(req.question, set(self.specs), self.today)
            if not m.metric:
                return self._finish(
                    QueryRequest(**req.model_dump()),
                    rid,
                    started,
                    ok=False,
                    error_code="metric_not_registered",
                    message="问题未命中任何已注册指标，strict 模式不予猜测",
                    hint="可先用 catalog 命令查看可用指标，或切到 exploratory 模式自行写 SQL",
                )
            spec = self.specs[m.metric]
            metric_name = spec.name
            start = req.start or m.start
            end = req.end or m.end
            if m.dimension and m.dimension not in spec.dimensions:
                alternatives = [d for d in (m.dimensions or []) if d in spec.dimensions]
                if alternatives:
                    dim = alternatives[0]
                    note = f"维度 {m.dimension} 不适用于 {spec.name}，改用 {dim}"
                else:
                    dim = None
                    note = f"维度 {m.dimension} 不被 {spec.name} 支持，已回退为整体值"
            else:
                dim = m.dimension
            sql, params = BUILDERS[spec.name](dim, start, end)
        else:
            if not req.sql:
                return self._finish(
                    req,
                    rid,
                    started,
                    ok=False,
                    error_code="sql_required",
                    message="exploratory 模式需要显式提供 SQL",
                    hint="传 --sql 'SELECT ...'；该 SQL 仍会经过 AST 策略审查",
                )
            sql, params = req.sql, []
            m = match(req.question, set(self.specs), self.today)
            if m.metric:
                spec = self.specs[m.metric]
                metric_name = spec.name

        # 2. AST policy
        verdict = review(sql)
        if not verdict.ok:
            fixed_sql, fixes = auto_fix(sql, verdict.codes)
            if fixes:
                recheck = review(fixed_sql)
                if recheck.ok:
                    sql, verdict, repaired = fixed_sql, recheck, len(fixes)
                    note = (note + "；" if note else "") + "自动修复：" + ", ".join(fixes)
        if not verdict.ok:
            return self._finish(
                req,
                rid,
                started,
                ok=False,
                metric=metric_name,
                dimension=dim,
                sql=sql,
                error_code=f"policy_blocked:{verdict.summary()}",
                message="SQL 未通过策略审查",
                hint="; ".join(f"{f.code}: {f.detail}" for f in verdict.findings),
                ast_verdict=verdict.summary(),
            )

        # 3. definition check
        if spec is not None:
            issues = verify(sql, spec)
            if issues:
                return self._finish(
                    req,
                    rid,
                    started,
                    ok=False,
                    metric=metric_name,
                    dimension=dim,
                    sql=sql,
                    error_code="definition_mismatch",
                    message="生成 SQL 与指标口径不一致",
                    hint="; ".join(issues),
                    ast_verdict=verdict.summary(),
                )

        # 4. execute
        result = self.engine.run(sql, params)
        if not result.ok:
            code, hint = classify(result.error)
            return self._finish(
                req,
                rid,
                started,
                ok=False,
                metric=metric_name,
                dimension=dim,
                sql=sql,
                error_code=code,
                message=result.error[:300],
                hint=hint,
                ast_verdict=verdict.summary(),
                repaired=repaired,
            )

        # 5. mask
        rows, masked = mask_rows(result.rows, result.columns)
        value = None
        if dim and spec is not None:
            # A grouped row is not the total. Compute the overall value with the
            # same compiler, so the headline number can never be a single group.
            overall_sql, overall_params = BUILDERS[spec.name](None, start, end)
            overall = self.engine.run(overall_sql, overall_params)
            if overall.ok and overall.rows:
                try:
                    value = float(overall.rows[0]["v"])
                except (TypeError, ValueError):
                    value = None
        elif rows and "v" in rows[0]:
            try:
                value = float(rows[0]["v"])
            except (TypeError, ValueError):
                value = None

        return self._finish(
            req,
            rid,
            started,
            ok=True,
            metric=metric_name,
            dimension=dim,
            sql=sql,
            value=value,
            rows=rows,
            row_count=result.row_count,
            message=note or ("ok" if not result.truncated else "结果已截断至行数上限"),
            masked_columns=masked,
            ast_verdict=verdict.summary(),
            repaired=repaired,
        )

    # ------------------------------------------------------------------
    def _finish(self, req: QueryRequest, rid: str, started: float, **kwargs) -> QueryResult:
        latency = round((time.perf_counter() - started) * 1000, 2)
        payload = {
            "request_id": rid,
            "mode": req.mode,
            "latency_ms": latency,
            **kwargs,
        }
        payload.setdefault("rows", [])
        payload.setdefault("row_count", 0)
        payload.setdefault("ok", False)
        result = QueryResult(**payload)
        self.audit.write(
            {
                "request_id": rid,
                "question": req.question,
                "mode": req.mode,
                "metric": result.metric,
                "dimension": result.dimension,
                "sql": result.sql,
                "sql_hash": hashlib.sha256(result.sql.encode()).hexdigest()[:16] if result.sql else "",
                "ast_verdict": result.ast_verdict,
                "ok": result.ok,
                "error_code": result.error_code,
                "row_count": result.row_count,
                "latency_ms": latency,
                "masked_columns": result.masked_columns,
                "repaired": result.repaired,
                "user_scope": req.user_scope,
            }
        )
        return result

    def close(self) -> None:
        self.engine.close()
