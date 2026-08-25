"""Freeze P9.K.0 publication, execution-agent, and route ownership boundaries."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).parents[2]
API_ROOT = ROOT / "packages/api/onlyalpha-api/src/onlyalpha_api"
RESEARCH_EXECUTION_ROOT = ROOT / "src/onlyalpha/research/execution"

HTTP_METHODS = {"delete", "get", "head", "options", "patch", "post", "put", "trace"}
EXPECTED_HTTP_ROUTE_MODULES = {
    "packages/api/onlyalpha-api/src/onlyalpha_api/health.py",
    "packages/api/onlyalpha-api/src/onlyalpha_api/research/definition_routes.py",
    "packages/api/onlyalpha-api/src/onlyalpha_api/research/routes.py",
    "packages/api/onlyalpha-api/src/onlyalpha_api/research/run_routes.py",
}

FORBIDDEN_ROUTE_IMPORTS = (
    "onlyalpha.application.strategy_authority",
    "onlyalpha.engine",
    "onlyalpha.persistence",
    "onlyalpha.runtime",
    "onlyalpha.strategy.freeze",
    "onlyalpha.strategy.promotion",
    "onlyalpha.strategy.store",
    "onlyalpha.research.execution",
    "onlyalpha.kernel",
    "onlyalpha.broker",
)
FORBIDDEN_ROUTE_CAPABILITIES = (
    "OnlyStrategyFreezeApplicationService",
    "OnlyStrategyPromotionApplicationService",
    "OnlyStrategyFreezeService",
    "OnlyStrategyPromotionService",
    "OnlyStrategyRevisionStore",
    "_OnlyFrozenStrategyPublisher",
    "_only_compose_frozen_strategy_authority",
    "OnlyResearchWorkerService",
    "OnlyPostgresMigrationAuthority",
)

EXPECTED_CLI_ONLYALPHA_IMPORTS = {
    ("onlyalpha.application", "OnlyEngineInspectionService"),
    ("onlyalpha.application.engine_runner", "OnlyEngineApplicationRunner"),
    ("onlyalpha.application.engine_runner", "OnlyRuntimeLifecycleKind"),
    ("onlyalpha.application.engine_runner", "only_engine_lifecycle_kind"),
    ("onlyalpha.core.errors", "OnlyError"),
    ("onlyalpha.domain.identifiers", "OnlyEngineId"),
    ("onlyalpha.engine", "OnlyEngine"),
    ("onlyalpha.engine", "OnlyEngineConfig"),
    ("onlyalpha.persistence.postgres", "OnlyPostgresConfig"),
    ("onlyalpha.persistence.postgres", "OnlyPostgresResearchOperationsStore"),
    ("onlyalpha.research.operations.diagnostics", "OnlyResearchOperationalDiagnosticService"),
    ("onlyalpha.research.run", "OnlyResearchRunId"),
    ("onlyalpha.runtime.defaults", "only_default_engine_services"),
    ("onlyalpha.scenario", "OnlyMarketScenarioParser"),
    ("onlyalpha.scenario", "OnlyMarketScenarioRunRequest"),
    ("onlyalpha.scenario", "OnlyMarketScenarioRunner"),
}

FORBIDDEN_WORKER_IMPORTS = (
    "onlyalpha.application.strategy_authority",
    "onlyalpha.strategy.freeze",
    "onlyalpha.strategy.promotion",
    "onlyalpha.persistence.postgres.strategy_store",
    "onlyalpha.kernel",
    "onlyalpha.broker",
    "onlyalpha.runtime.live",
)
FORBIDDEN_WORKER_CAPABILITIES = (
    "OnlyStrategyFreezeApplicationService",
    "OnlyStrategyPromotionApplicationService",
    "OnlyStrategyFreezeService",
    "OnlyStrategyPromotionService",
    "_OnlyFrozenStrategyPublisher",
    "_only_compose_frozen_strategy_authority",
    "OnlyLiveRuntime",
)


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            result.append(node.module)
    return tuple(result)


def _source_imported_capabilities(source: str) -> set[tuple[str, str]]:
    tree = ast.parse(source)
    return {
        (node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
        for alias in node.names
    }


def _imported_capabilities(path: Path) -> set[tuple[str, str]]:
    return _source_imported_capabilities(path.read_text(encoding="utf-8"))


def _defines_http_route(path: Path) -> bool:
    return _source_defines_http_route(path.read_text(encoding="utf-8"))


def _source_defines_http_route(source: str) -> bool:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        decorators = node.decorator_list if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else ()
        for decorator in decorators:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if isinstance(target, ast.Attribute) and target.attr in HTTP_METHODS | {"api_route"}:
                return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_api_route":
            return True
    return False


def _assert_no_forbidden_capability(
    path: Path,
    *,
    forbidden_imports: tuple[str, ...],
    forbidden_capabilities: tuple[str, ...],
) -> None:
    imports = _imports(path)
    for imported in imports:
        assert not imported.startswith(forbidden_imports), (
            f"{path.relative_to(ROOT)} imports forbidden authority {imported}"
        )
    imported_names = {name for _, name in _imported_capabilities(path)}
    for capability in forbidden_capabilities:
        assert capability not in imported_names, f"{path.relative_to(ROOT)} obtains {capability}"


def test_api_routes_do_not_own_semantic_or_infrastructure_writers() -> None:
    route_paths = tuple(path for path in sorted(API_ROOT.rglob("*.py")) if _defines_http_route(path))
    assert {path.relative_to(ROOT).as_posix() for path in route_paths} == EXPECTED_HTTP_ROUTE_MODULES
    for path in route_paths:
        _assert_no_forbidden_capability(
            path,
            forbidden_imports=FORBIDDEN_ROUTE_IMPORTS,
            forbidden_capabilities=FORBIDDEN_ROUTE_CAPABILITIES,
        )


def test_unexpected_route_filename_is_still_detected() -> None:
    source = (
        "from onlyalpha.application.strategy_authority import OnlyStrategyPromotionApplicationService\n"
        "router = object()\n@router.post('/strategy')\ndef publish(): pass\n"
    )
    assert _source_defines_http_route(source)
    assert (
        "onlyalpha.application.strategy_authority",
        "OnlyStrategyPromotionApplicationService",
    ) in _source_imported_capabilities(source)
    assert "onlyalpha.application.strategy_authority" in FORBIDDEN_ROUTE_IMPORTS
    assert "OnlyStrategyPromotionApplicationService" in FORBIDDEN_ROUTE_CAPABILITIES


def test_cli_capability_set_is_frozen() -> None:
    cli = ROOT / "src/onlyalpha/cli.py"
    actual = {(module, name) for module, name in _imported_capabilities(cli) if module.startswith("onlyalpha")}
    assert actual == EXPECTED_CLI_ONLYALPHA_IMPORTS


def test_cli_new_strategy_mutation_capability_changes_the_frozen_set() -> None:
    source = "from onlyalpha.application.strategy_authority import OnlyStrategyPromotionApplicationService\n"
    assert _source_imported_capabilities(source) != EXPECTED_CLI_ONLYALPHA_IMPORTS


def test_research_worker_remains_execution_agent_without_strategy_product_authority() -> None:
    paths = (ROOT / "src/onlyalpha/research/worker_main.py", *sorted(RESEARCH_EXECUTION_ROOT.glob("*.py")))
    for path in paths:
        _assert_no_forbidden_capability(
            path,
            forbidden_imports=FORBIDDEN_WORKER_IMPORTS,
            forbidden_capabilities=FORBIDDEN_WORKER_CAPABILITIES,
        )


def test_scheduler_cannot_obtain_strategy_promotion_capability() -> None:
    source = (
        "from onlyalpha.application.strategy_authority import OnlyStrategyPromotionApplicationService as Promotion\n"
    )
    capabilities = _source_imported_capabilities(source)
    assert ("onlyalpha.application.strategy_authority", "OnlyStrategyPromotionApplicationService") in capabilities
    assert "onlyalpha.application.strategy_authority" in FORBIDDEN_WORKER_IMPORTS
    assert "OnlyStrategyPromotionApplicationService" in FORBIDDEN_WORKER_CAPABILITIES


def test_projection_reconciliation_is_operator_infrastructure_only() -> None:
    report = (ROOT / "docs/reports/p9_k0_product_surface_inventory.md").read_text(encoding="utf-8")
    row = next(line for line in report.splitlines() if line.startswith("| K0-S022 |"))
    assert "OPERATOR / INFRASTRUCTURE ONLY" in row
    assert "`KEEP INTERNAL`" not in row


def test_strategy_publication_capability_remains_freeze_owned() -> None:
    allowed = {
        ROOT / "src/onlyalpha/application/strategy_authority.py",
        ROOT / "src/onlyalpha/strategy/freeze.py",
        ROOT / "src/onlyalpha/strategy/store.py",
    }
    actual = {
        path
        for path in (ROOT / "src/onlyalpha").rglob("*.py")
        if "_OnlyFrozenStrategyPublisher" in path.read_text(encoding="utf-8")
        or "_only_compose_frozen_strategy_authority" in path.read_text(encoding="utf-8")
    }
    assert actual == allowed
