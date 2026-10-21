from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class MetricSpec(BaseModel):
    """A metric contract.

    `numerator` / `denominator` are human-readable statements of the ratio, not
    SQL fragments -- the executable form lives in `catalog/builders.py`. Keeping
    them separate forces the definition and the implementation to be reviewed
    independently, which is the whole point of a semantic layer.
    """

    name: str
    label: str
    version: int = Field(default=1, ge=1)
    owner: str
    unit: str
    kind: Literal["ratio", "aggregate"]
    description: str
    numerator: str
    denominator: str | None = None
    dimensions: list[str] = Field(default_factory=list)
    pii_columns: list[str] = Field(default_factory=list)
    expected_aggregates: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_kind(self) -> MetricSpec:
        if self.kind == "ratio" and not self.denominator:
            raise ValueError(f"metric {self.name}: ratio requires a denominator")
        if self.kind == "aggregate" and self.denominator:
            raise ValueError(f"metric {self.name}: aggregate must not declare a denominator")
        if not self.dimensions:
            raise ValueError(f"metric {self.name}: at least one dimension is required")
        return self


class QueryRequest(BaseModel):
    question: str
    mode: Literal["strict", "exploratory"] = "strict"
    start: str = ""
    end: str = ""
    sql: str | None = None
    user_scope: str = "analyst"


class QueryResult(BaseModel):
    request_id: str
    ok: bool
    mode: str
    metric: str | None = None
    dimension: str | None = None
    sql: str = ""
    value: float | None = None
    rows: list[dict] = Field(default_factory=list)
    row_count: int = 0
    error_code: str | None = None
    message: str = ""
    hint: str = ""
    repaired: int = 0
    masked_columns: list[str] = Field(default_factory=list)
    latency_ms: float = 0.0
    ast_verdict: str = ""
