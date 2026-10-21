"""Read-only DuckDB execution with a hard row cap."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import duckdb

TABLES = (
    "members",
    "products",
    "orders",
    "order_items",
    "behaviors",
    "campaigns",
    "campaign_assignments",
)


@dataclass
class ExecResult:
    ok: bool
    columns: list[str] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    latency_ms: float = 0.0
    error: str = ""


class Engine:
    def __init__(self, data_dir: str | Path, max_rows: int = 5000) -> None:
        self.data_dir = Path(data_dir)
        self.max_rows = max_rows
        missing = [t for t in TABLES if not (self.data_dir / f"{t}.parquet").exists()]
        if missing:
            raise FileNotFoundError(f"missing fixtures: {missing}")
        self._con = duckdb.connect(database=":memory:", config={"memory_limit": "512MB"})
        for table in TABLES:
            path = (self.data_dir / f"{table}.parquet").as_posix()
            self._con.execute(
                f"CREATE OR REPLACE VIEW {table} AS SELECT * FROM read_parquet('{path}')"
            )

    def run(self, sql: str, params: Sequence[Any] | None = None) -> ExecResult:
        started = time.perf_counter()
        try:
            cur = self._con.execute(sql, list(params or []))
            columns = [d[0] for d in cur.description] if cur.description else []
            fetched = cur.fetchmany(self.max_rows + 1)
        except Exception as exc:  # noqa: BLE001
            return ExecResult(
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )

        truncated = len(fetched) > self.max_rows
        fetched = fetched[: self.max_rows]
        rows = [dict(zip(columns, row)) for row in fetched]
        return ExecResult(
            ok=True,
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    def close(self) -> None:
        self._con.close()
