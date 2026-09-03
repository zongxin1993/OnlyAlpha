from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture
ROOT = Path(__file__).parents[2]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
    return imported


def test_http_backtest_transport_cannot_import_or_invoke_engine() -> None:
    root = ROOT / "packages/onlyalpha-http-server/src/onlyalpha_http_server/backtest"
    for path in root.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert not any(name.startswith("onlyalpha.engine") for name in _imports(path))
        assert "OnlyEngine(" not in source
        assert ".run()" not in source


def test_worker_is_the_only_backtest_product_to_engine_bridge() -> None:
    root = ROOT / "src/onlyalpha/backtest"
    importers = {
        path.name for path in root.glob("*.py") if any(name.startswith("onlyalpha.engine") for name in _imports(path))
    }
    assert importers == {"worker.py"}
    worker = (root / "worker.py").read_text(encoding="utf-8")
    assert "class OnlyEngineBacktestRuntimeExecutor" in worker
    assert "OnlyEngine(" in worker
    assert "deepcopy" not in worker
    assert "document.normalized_payload" not in worker


def test_operator_deployment_catalog_retains_only_market_resources() -> None:
    deployment = (ROOT / "src/onlyalpha/backtest/deployment.py").read_text(encoding="utf-8")

    resource = deployment.split("class OnlyBacktestProductResourceDocument", 1)[1].split(
        "class OnlyBacktestDeploymentCatalog", 1
    )[0]
    for forbidden in ("brokers", "accounts", "strategy", "risk", "portfolio", "slippage", "matching"):
        assert forbidden not in resource


def test_backtest_core_has_no_concrete_provider_or_mutable_query_path() -> None:
    root = ROOT / "src/onlyalpha/backtest"
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    lowered = source.lower()
    for forbidden in ("onlyalpha_plugin_binance", "onlyalpha_plugin_miniqmt", "tushare", "qmt", "ctp"):
        assert forbidden not in lowered
    assert "select * from" not in lowered
    assert "mutable database" not in lowered
    assert "load_verified_table" in source


def test_compose_acceptance_client_is_http_only_and_has_no_product_credentials() -> None:
    path = ROOT / "deploy/compose/product_acceptance_client.py"
    imports = _imports(path)
    source = path.read_text(encoding="utf-8")

    assert not any(name == "onlyalpha" or name.startswith("onlyalpha.") for name in imports)
    assert "ONLYALPHA_POSTGRES" not in source
    assert "ONLYALPHA_CLICKHOUSE" not in source
    assert "user-data" not in source
    assert "OnlyEngine" not in source
    assert "urllib.request" in imports
