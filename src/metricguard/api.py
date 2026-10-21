"""FastAPI wrapper around the gateway."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .audit.log import AuditLog
from .catalog.loader import catalog_summary
from .catalog.models import QueryRequest
from .gateway import Gateway
from .paths import audit_path, catalog_dir, explain, fixtures_dir, is_repo

WEB = Path(__file__).parent / "web" / "index.html"

app = FastAPI(title="metricguard", version="0.1.0", description="指标口径守卫与可信问数网关")
_gateway: Gateway | None = None


def gateway() -> Gateway:
    global _gateway
    if _gateway is None:
        if not is_repo():
            raise RuntimeError(explain())
        _gateway = Gateway(catalog_dir(), fixtures_dir(), audit_path())
    return _gateway


class AskBody(BaseModel):
    question: str
    mode: str = "strict"
    start: str = ""
    end: str = ""
    sql: str | None = None


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return WEB.read_text(encoding="utf-8")


@app.get("/api/catalog")
def catalog() -> list[dict]:
    return catalog_summary(gateway().specs)


@app.post("/api/ask")
def ask(body: AskBody) -> dict:
    result = gateway().ask(
        QueryRequest(
            question=body.question,
            mode=body.mode,  # type: ignore[arg-type]
            start=body.start,
            end=body.end,
            sql=body.sql,
        )
    )
    return result.model_dump()


@app.get("/api/audit")
def audit(tail: int = 20) -> list[dict]:
    return AuditLog(audit_path()).tail(tail)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "metrics": len(gateway().specs)}
