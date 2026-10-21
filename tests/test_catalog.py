import pytest

from metricguard.catalog.builders import BUILDERS
from metricguard.catalog.loader import CatalogError, load_catalog
from metricguard.catalog.models import MetricSpec


def test_catalog_has_twelve_metrics(specs):
    assert len(specs) == 12


def test_every_metric_has_an_implementation(specs):
    assert set(specs) == set(BUILDERS)


def test_ratio_requires_denominator():
    with pytest.raises(ValueError):
        MetricSpec(
            name="x",
            label="x",
            owner="o",
            unit="%",
            kind="ratio",
            description="d",
            numerator="sum(a)",
            dimensions=["channel"],
        )


def test_aggregate_rejects_denominator():
    with pytest.raises(ValueError):
        MetricSpec(
            name="x",
            label="x",
            owner="o",
            unit="元",
            kind="aggregate",
            description="d",
            numerator="sum(a)",
            denominator="count(*)",
            dimensions=["channel"],
        )


def test_duplicate_metric_is_rejected(tmp_path):
    body = """
metrics:
  - name: aov
    label: a
    owner: o
    unit: yuan
    kind: ratio
    description: d
    numerator: sum(x)
    denominator: count(*)
    dimensions: [channel]
"""
    (tmp_path / "a.yml").write_text(body, encoding="utf-8")
    (tmp_path / "b.yml").write_text(body, encoding="utf-8")
    with pytest.raises(CatalogError):
        load_catalog(tmp_path)
