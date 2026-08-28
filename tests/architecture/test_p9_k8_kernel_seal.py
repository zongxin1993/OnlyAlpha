"""Permanent negative architecture gate for the P9.K.8 Product authority seal."""

from __future__ import annotations

import ast
import importlib
import tomllib
from pathlib import Path

import pytest

from tests.architecture._p9_k0_authority_contract import load_authority_contract
from tests.architecture.test_p9_k0_product_surfaces import (
    EXPECTED_DIRECT_CONSTRUCTION_CLASSIFICATION,
    HISTORICAL_ROOT_MIGRATION_DEBT,
    ROOT_KNOWN_MIGRATION_DEBT,
    _console_entry_points,
    _direct_construction_sites,
)

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).parents[2]
API_SOURCE = ROOT / "packages/api/onlyalpha-api/src/onlyalpha_api"
CLIENT_SOURCE = ROOT / "packages/client/onlyalpha-client/src/onlyalpha_client"
WEB_SOURCE = ROOT / "apps/onlyalpha-web/src"


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
    assert HISTORICAL_ROOT_MIGRATION_DEBT == {
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
    assert ROOT_KNOWN_MIGRATION_DEBT == frozenset()
    forbidden_by_module = {
        "onlyalpha": HISTORICAL_ROOT_MIGRATION_DEBT,
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


def test_root_cli_has_only_explicit_operator_and_scenario_families() -> None:
    source = (ROOT / "src/onlyalpha/cli.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    command_names = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_parser"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }
    assert command_names == {"operations", "run", "scenario", "status", "validate"}
    assert 'subparsers.add_parser("run")' not in source
    assert 'subparsers.add_parser("snapshot")' not in source
    assert "OnlyEngine" not in source
    assert "OnlyEngineApplicationRunner" not in source
    assert "onlyalpha.engine" not in _imports(ROOT / "src/onlyalpha/cli.py")


def test_official_product_client_and_web_have_no_core_or_local_fallback_capability() -> None:
    forbidden_imports = (
        "onlyalpha",
        "onlyalpha_api",
        "onlyalpha_gateway_protocol",
    )
    forbidden_fallback_tokens = (
        "OnlyEngine",
        "OnlyRuntime",
        "run_local",
        "local_fallback",
        "only_default_engine_services",
    )
    for path in CLIENT_SOURCE.rglob("*.py"):
        assert not any(
            name == prefix or name.startswith(f"{prefix}.") for name in _imports(path) for prefix in forbidden_imports
        ), path
        if "generated" not in path.parts:
            source = path.read_text(encoding="utf-8")
            assert not any(token in source for token in forbidden_fallback_tokens), path
    for path in WEB_SOURCE.rglob("*"):
        if path.suffix in {".ts", ".tsx"}:
            source = path.read_text(encoding="utf-8")
            assert not any(
                token in source for token in ("OnlyEngine", "onlyalpha.kernel", "onlyalpha_gateway_protocol")
            ), path


def test_http_route_modules_own_no_raw_mutation_capability() -> None:
    routes = _route_modules()
    assert {path.relative_to(API_SOURCE).as_posix() for path in routes} == {
        "health.py",
        "research/definition_routes.py",
        "research/routes.py",
        "research/run_routes.py",
    }
    forbidden_prefixes = (
        "onlyalpha.engine",
        "onlyalpha.runtime",
        "onlyalpha.kernel",
        "onlyalpha.persistence",
        "onlyalpha.strategy",
        "onlyalpha_gateway_protocol",
    )
    forbidden_symbols = (
        "OnlyAlphaKernelHost",
        "OnlyEngine",
        "OnlyPostgres",
        "OnlyResearchCommandService",
        "OnlyStrategyFreeze",
        "OnlyStrategyPromotion",
    )
    for path in routes:
        imports = _imports(path)
        assert not any(name.startswith(forbidden_prefixes) for name in imports), path
        assert not any(
            name.startswith("onlyalpha.application") and name != "onlyalpha.application.product_boundary"
            for name in imports
        ), path
        source = path.read_text(encoding="utf-8")
        assert not any(symbol in source for symbol in forbidden_symbols), path
    run_source = (API_SOURCE / "research/run_routes.py").read_text(encoding="utf-8")
    assert run_source.count("product.commands.dispatch(") == 2
    assert run_source.count("product.queries.dispatch(") == 2


def test_product_space_has_zero_direct_engine_or_runtime_constructor_owner() -> None:
    sites = _direct_construction_sites()
    assert sites == set(EXPECTED_DIRECT_CONSTRUCTION_CLASSIFICATION)
    assert all(
        classification in {"ALLOWED INTERNAL", "OPERATOR / INFRASTRUCTURE", "TEST TOOLING"}
        for classification in EXPECTED_DIRECT_CONSTRUCTION_CLASSIFICATION.values()
    )
    forbidden_roots = ("apps/", "packages/client/", "examples/product/")
    assert not any(path.startswith(forbidden_roots) or path == "src/onlyalpha/cli.py" for path, _ in sites)


def test_k0_and_k6_migration_debt_is_zero_and_all_external_surfaces_are_classified() -> None:
    k0 = load_authority_contract(ROOT / "docs/architecture/p9_k0_authority_contract.toml")
    assert k0.legacy_debts == {}
    k6 = tomllib.loads((ROOT / "docs/architecture/p9_k6_external_client_contract.toml").read_text(encoding="utf-8"))
    surfaces = k6["external_surfaces"]
    commands = k6["cli_commands"]
    assert not any(item["classification"] == "LEGACY_K8_TARGET" for item in (*surfaces, *commands))
    assert not any(item["k8_debt"] for item in (*surfaces, *commands))
    assert all(item["classification"] not in {"UNKNOWN", "UNCLASSIFIED"} for item in (*surfaces, *commands))


def test_standalone_artifact_compatibility_product_surface_is_absent() -> None:
    entry_points = _console_entry_points()
    assert not any(name == "onlyalpha-artifact-api" for _, name, _ in entry_points)
    assert not (API_SOURCE / "artifact_main.py").exists()
    app_source = (API_SOURCE / "app.py").read_text(encoding="utf-8")
    package_source = (API_SOURCE / "__init__.py").read_text(encoding="utf-8")
    assert "create_artifact_query_app" not in app_source
    assert "create_artifact_query_app" not in package_source
    assert "create_artifact_router(artifact_service)" in app_source


def test_composition_root_retains_real_kernel_wiring_without_route_ownership() -> None:
    main = (API_SOURCE / "main.py").read_text(encoding="utf-8")
    assert main.count("OnlyAlphaKernelHost(") == 1
    assert "OnlyPostgresResearchRunStore(" in main
    assert "only_compose_research_product_boundary(" in main
    assert "create_research_app(" in main
