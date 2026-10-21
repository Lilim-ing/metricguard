from pathlib import Path

import pytest

from metricguard.catalog.loader import load_catalog
from metricguard.gateway import Gateway

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog" / "metrics"
DATA = ROOT / "data" / "fixtures"


@pytest.fixture(scope="session")
def specs():
    return load_catalog(CATALOG)


@pytest.fixture(scope="session")
def gw(tmp_path_factory):
    audit = tmp_path_factory.mktemp("audit") / "audit.jsonl"
    gateway = Gateway(CATALOG, DATA, audit)
    yield gateway
    gateway.close()
