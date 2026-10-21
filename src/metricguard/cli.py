"""Command line entry point."""

from __future__ import annotations

import sys

import typer
from rich.console import Console
from rich.table import Table

from .catalog.loader import catalog_summary, load_catalog
from .catalog.models import QueryRequest
from .gateway import Gateway
from .paths import audit_path, catalog_dir, explain, fixtures_dir, is_repo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

app = typer.Typer(add_completion=False, help="metricguard · 指标口径守卫与可信问数网关")
console = Console()


def _require_repo() -> None:
    if not is_repo():
        raise typer.BadParameter(explain())


@app.command()
def ask(
    question: str = typer.Argument(..., help="自然语言问题"),
    mode: str = typer.Option("strict", help="strict | exploratory"),
    start: str = typer.Option("", help="开始日期 YYYY-MM-DD"),
    end: str = typer.Option("", help="结束日期 YYYY-MM-DD"),
    sql: str = typer.Option("", help="exploratory 模式下显式提供的 SQL"),
    today: str = typer.Option("2026-09-30", help="相对时间的基准日"),
    json_out: bool = typer.Option(False, "--json", help="输出完整 JSON"),
) -> None:
    """提出一个指标问题。"""
    _require_repo()
    gw = Gateway(catalog_dir(), fixtures_dir(), audit_path(), today=today)
    try:
        result = gw.ask(
            QueryRequest(
                question=question,
                mode=mode,  # type: ignore[arg-type]
                start=start,
                end=end,
                sql=sql or None,
            )
        )
    finally:
        gw.close()

    if json_out:
        console.print_json(result.model_dump_json())
        return

    if not result.ok:
        console.print(f"[red]拒绝[/red] {result.error_code}")
        console.print(f"  {result.message}")
        if result.hint:
            console.print(f"  [dim]hint: {result.hint}[/dim]")
        raise typer.Exit(code=2)

    console.print(f"[green]通过[/green] {result.metric} · {result.mode} · {result.latency_ms}ms · {result.ast_verdict}")
    if result.value is not None:
        console.print(f"  整体值：[bold]{result.value:.4f}[/bold]")
    if result.rows:
        cols = list(result.rows[0].keys())
        table = Table(show_header=True, header_style="bold")
        for c in cols:
            table.add_column(c)
        for row in result.rows[:20]:
            table.add_row(*[f"{v:.4f}" if isinstance(v, float) else str(v) for v in row.values()])
        console.print(table)
    if result.message and result.message != "ok":
        console.print(f"  [dim]{result.message}[/dim]")
    console.print(f"  [dim]audit: {result.request_id}[/dim]")


@app.command("catalog")
def catalog_cmd() -> None:
    """列出已注册指标。"""
    _require_repo()
    specs = load_catalog(catalog_dir())
    table = Table(show_header=True, header_style="bold")
    table.add_column("指标")
    table.add_column("名称")
    table.add_column("单位")
    table.add_column("版本")
    table.add_column("维度")
    for item in catalog_summary(specs):
        table.add_row(
            item["name"], item["label"], item["unit"], str(item["version"]), ", ".join(item["dimensions"])
        )
    console.print(table)


@app.command()
def audit(tail: int = typer.Option(10, help="最近 N 条")) -> None:
    """查看审计日志。"""
    from .audit.log import AuditLog

    _require_repo()
    records = AuditLog(audit_path()).tail(tail)
    table = Table(show_header=True, header_style="bold")
    for col in ("request_id", "mode", "metric", "ok", "error_code", "rows", "ms"):
        table.add_column(col)
    for r in records:
        table.add_row(
            str(r.get("request_id")),
            str(r.get("mode")),
            str(r.get("metric")),
            "✅" if r.get("ok") else "❌",
            str(r.get("error_code") or ""),
            str(r.get("row_count")),
            str(r.get("latency_ms")),
        )
    console.print(table)


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8134) -> None:
    """启动 Web 问数界面。"""
    import uvicorn

    _require_repo()
    uvicorn.run("metricguard.api:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    app()
