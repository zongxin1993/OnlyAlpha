"""Permanent negative architecture gate for Product authority boundaries."""

from __future__ import annotations

import ast
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.architecture._product_authority_contract import load_authority_contract
from tests.architecture.test_product_surface_boundaries import (
    EXPECTED_DIRECT_CONSTRUCTION_CLASSIFICATION,
    FORBIDDEN_ROOT_CONSTRUCTOR_EXPORTS,
    _console_entry_points,
    _direct_construction_sites,
)

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).parents[2]
API_SOURCE = ROOT / "packages/onlyalpha-http-server/src/onlyalpha_http_server"
WEB_SOURCE = ROOT / "packages/onlyalpha-web-console/src"


@pytest.mark.parametrize(
    ("statement", "sentinel"),
    (
        ("from onlyalpha.runtime.sim.runtime import OnlySimRuntime", "SIM_IMPORT_OK"),
        ("from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime", "BACKTEST_IMPORT_OK"),
    ),
)
def test_concrete_trading_runtime_bootstrap_is_fresh_process_deterministic(
    statement: str,
    sentinel: str,
) -> None:
    completed = subprocess.run(
        [sys.executable, "-c", f'{statement}; print("{sentinel}")'],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == sentinel


def _imports(path: Path) -> frozenset[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
    return frozenset(imported)


def _route_modules() -> frozenset[Path]:
    result: set[Path] = set()
    for path in API_SOURCE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr in {"delete", "get", "patch", "post", "put"}
                for decorator in node.decorator_list
            ):
                result.add(path)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_api_route"
            ):
                result.add(path)
    return frozenset(result)


def test_root_and_broad_aggregators_expose_zero_mutation_constructors() -> None:
    assert FORBIDDEN_ROOT_CONSTRUCTOR_EXPORTS == {
        "OnlyBacktestRuntime",
        "OnlyCluster",
        "OnlyClusterConfig",
        "OnlyClusterContext",
        "OnlyClusterLoader",
        "OnlyClusterRegistry",
        "OnlyClusterRunConfig",
        "OnlyDemoCluster",
        "OnlyDemoRecord",
        "OnlyEngine",
        "OnlyLiveRuntime",
        "OnlyResearchRuntime",
        "OnlyRuntime",
    }
    forbidden_by_module = {
        "onlyalpha": FORBIDDEN_ROOT_CONSTRUCTOR_EXPORTS,
        "onlyalpha.engine": {"OnlyEngine"},
        "onlyalpha.runtime": {
            "OnlyBacktestRuntime",
            "OnlyLiveRuntime",
            "OnlyResearchRuntime",
            "OnlyRuntime",
            "OnlySimRuntime",
        },
        "onlyalpha.cluster": {
            "OnlyCluster",
            "OnlyClusterConfig",
            "OnlyClusterContext",
            "OnlyClusterManager",
        },
    }
    for module_name, forbidden in forbidden_by_module.items():
        module = importlib.import_module(module_name)
        assert forbidden.isdisjoint(vars(module)), module_name
        assert forbidden.isdisjoint(getattr(module, "__all__", ())), module_name
        assert all(not hasattr(module, name) for name in forbidden), module_name


def test_root_product_cli_is_absent() -> None:
    assert not (ROOT / "src/onlyalpha/cli.py").exists()
    assert not any(path == "pyproject.toml" and name == "onlyalpha" for path, name, _ in _console_entry_points())


def test_web_has_no_core_or_local_fallback_capability() -> None:
    assert not (ROOT / "packages/client/onlyalpha-client").exists()
    for path in WEB_SOURCE.rglob("*"):
        if path.suffix in {".ts", ".tsx"}:
            source = path.read_text(encoding="utf-8")
            assert not any(
                token in source for token in ("OnlyEngine", "onlyalpha.kernel", "onlyalpha_gateway_protocol")
            ), path


def test_http_route_modules_own_no_raw_mutation_capability() -> None:
    assert not _route_modules()
    assert not tuple(API_SOURCE.rglob("*.py"))
    source = (ROOT / "packages/onlyalpha-http-server/rust/routes.rs").read_text()
    assert "host::Host" in source and "host.dispatch(request).await" in source
    for forbidden in (
        "onlyalpha_kernel",
        "onlyalpha_predicates",
        "tokio_postgres",
        "AuthoritySession",
        "OnlyEngine",
        "OnlyResearchCommandService",
    ):
        assert forbidden not in source
    native = json.loads((ROOT / "contracts/product-api/v2/openapi.json").read_text())
    assert set(native["paths"]["/api/v2/research/runs"]["post"]["responses"]) == {"501"}


def test_market_discovery_queries_have_no_mutation_or_store_dependency() -> None:
    permitted = {
        "onlyalpha.application.market_data_product",
        "onlyalpha.application.source_read_access",
        "onlyalpha.domain.enums",
        "onlyalpha.domain.instrument",
        "onlyalpha.plugin.data_source",
    }
    owning_calls: set[str] = set()
    for module in ("market_data_discovery", "market_data_discovery_worker"):
        path = ROOT / f"src/onlyalpha/application/{module}.py"
        assert {name for name in _imports(path) if name.startswith("onlyalpha")} <= permitted
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "_market_data"
            ):
                owning_calls.add(node.func.attr)
    assert owning_calls == {"list_sources", "resolve_read_runtime"}


def test_product_space_has_zero_direct_engine_or_runtime_constructor_owner() -> None:
    sites = _direct_construction_sites()
    assert sites == set(EXPECTED_DIRECT_CONSTRUCTION_CLASSIFICATION)
    assert all(
        classification in {"ALLOWED INTERNAL", "OPERATOR / INFRASTRUCTURE", "TEST TOOLING"}
        for classification in EXPECTED_DIRECT_CONSTRUCTION_CLASSIFICATION.values()
    )
    forbidden_roots = ("apps/", "packages/client/", "examples/")
    assert not any(path.startswith(forbidden_roots) or path == "src/onlyalpha/cli.py" for path, _ in sites)


def test_product_authority_migration_debt_is_zero() -> None:
    contract = load_authority_contract(ROOT / "docs/architecture/product_authority_contract.toml")
    assert contract.legacy_debts == {}


def test_standalone_artifact_compatibility_product_surface_is_absent() -> None:
    entry_points = _console_entry_points()
    assert not any(name in {"onlyalpha-artifact-api", "onlyalpha-api"} for _, name, _ in entry_points)
    assert not tuple(API_SOURCE.rglob("*.py"))


def test_composition_root_retains_real_kernel_wiring_without_route_ownership() -> None:
    assert not (API_SOURCE / "main.py").exists()
    native = ROOT / "packages/onlyalpha-http-server/rust"
    main = "".join(((native / "main.rs").read_text(encoding="utf-8")).split())
    startup = "".join(((native / "workstation_startup.rs").read_text(encoding="utf-8")).split())
    assert main.count("Running::open(config,&shutdown)") == 1
    assert startup.count("AuthoritySession::acquire(") == 1
    assert "inputs.verify(" in startup
    assert "#[utoipa::path" not in main + startup
    assert "OnlyEngine(" not in main + startup
