"""Repo-relative paths, resolved defensively.

`pip install -e .` keeps the package next to `catalog/` and `data/`. A plain
`pip install .` copies only the package into site-packages, so package-relative
paths point at `site-packages/../catalog` and everything breaks.

Resolution order: `METRICGUARD_HOME` -> package-relative -> cwd -> cwd/.. .
If none of them look like a repo, callers can ask for an explanation instead of
dumping a traceback on the user.
"""

from __future__ import annotations

import os
from pathlib import Path


def _looks_like_repo(path: Path) -> bool:
    return (path / "catalog" / "metrics").is_dir() and (
        path / "data" / "fixtures" / "members.parquet"
    ).exists()


def repo_root() -> Path:
    env = os.getenv("METRICGUARD_HOME")
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env))
    candidates += [
        Path(__file__).resolve().parents[2],
        Path.cwd(),
        Path(__file__).resolve().parents[3],
    ]
    for candidate in candidates:
        if _looks_like_repo(candidate):
            return candidate
    return candidates[0]


def is_repo(path: Path | None = None) -> bool:
    return _looks_like_repo(path or repo_root())


def catalog_dir() -> Path:
    return repo_root() / "catalog" / "metrics"


def fixtures_dir() -> Path:
    return repo_root() / "data" / "fixtures"


def audit_path() -> Path:
    return repo_root() / "audit_logs" / "audit.jsonl"


def explain(path: Path | None = None) -> str:
    root = path or repo_root()
    return (
        "找不到 metricguard 的 catalog/data。已尝试的根目录：\n"
        f"  - {root}\n"
        "解决方式：\n"
        '  1) 在仓库根目录用 editable 安装：pip install -e ".[dev]"\n'
        "  2) 在仓库根目录下运行（自动探测 ./catalog 与 ./data/fixtures）\n"
        "  3) 设置环境变量 METRICGUARD_HOME 指向仓库根目录"
    )
