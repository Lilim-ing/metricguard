from __future__ import annotations

from pathlib import Path

import yaml

from .models import MetricSpec


class CatalogError(RuntimeError):
    pass


def load_catalog(directory: str | Path) -> dict[str, MetricSpec]:
    directory = Path(directory)
    files = sorted(directory.glob("*.yml")) + sorted(directory.glob("*.yaml"))
    if not files:
        raise CatalogError(f"no metric files under {directory}")

    specs: dict[str, MetricSpec] = {}
    for path in files:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for raw in data.get("metrics", []):
            try:
                spec = MetricSpec(**raw)
            except Exception as exc:  # noqa: BLE001
                raise CatalogError(f"{path.name}: invalid metric {raw.get('name')!r}: {exc}") from exc
            if spec.name in specs:
                raise CatalogError(f"duplicate metric {spec.name!r}")
            specs[spec.name] = spec

    if not specs:
        raise CatalogError(f"no metrics defined under {directory}")
    return specs


def catalog_summary(specs: dict[str, MetricSpec]) -> list[dict]:
    return [
        {
            "name": s.name,
            "label": s.label,
            "unit": s.unit,
            "version": s.version,
            "kind": s.kind,
            "dimensions": s.dimensions,
            "description": s.description,
        }
        for s in specs.values()
    ]
