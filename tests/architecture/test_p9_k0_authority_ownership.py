"""Freeze P9.K.0 publication, execution-agent, and route ownership boundaries."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.architecture._p9_k0_guard_helpers import CanonicalImport, onlyalpha_imports

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

EXPECTED_ROUTE_ONLYALPHA_IMPORTS: dict[str, frozenset[CanonicalImport]] = {
    "packages/api/onlyalpha-api/src/onlyalpha_api/health.py": frozenset(
        {
            ("symbol", "onlyalpha.research.operations.readiness", "OnlyResearchReadiness"),
            ("symbol", "onlyalpha.research.operations.readiness", "OnlyResearchReadinessCheck"),
            ("symbol", "onlyalpha.research.operations.readiness", "OnlyResearchReadinessStatus"),
        }
    ),
    "packages/api/onlyalpha-api/src/onlyalpha_api/research/definition_routes.py": frozenset(),
    "packages/api/onlyalpha-api/src/onlyalpha_api/research/routes.py": frozenset(
        {
            ("symbol", "onlyalpha.research.query", "DEFAULT_PAGE_SIZE"),
            ("symbol", "onlyalpha.research.query", "OnlyResearchQueryService"),
            ("symbol", "onlyalpha.research.query", "OnlyResearchScientificSeriesQuery"),
            ("symbol", "onlyalpha.research.query", "OnlyResearchStatisticSeriesQuery"),
        }
    ),
    "packages/api/onlyalpha-api/src/onlyalpha_api/research/run_routes.py": frozenset(
        {
            ("symbol", "onlyalpha.research.command.errors", "OnlyResearchCommandError"),
            ("symbol", "onlyalpha.research.command.errors", "OnlyResearchCommandPhase"),
            ("symbol", "onlyalpha.research.command.model", "OnlyResearchSubmissionKey"),
            ("symbol", "onlyalpha.research.command.query", "DEFAULT_RESEARCH_RUN_PAGE_SIZE"),
            ("symbol", "onlyalpha.research.command.query", "OnlyResearchRunQueryService"),
            ("symbol", "onlyalpha.research.command.service", "OnlyResearchCommandService"),
            ("symbol", "onlyalpha.research.run.model", "OnlyResearchRunId"),
            ("symbol", "onlyalpha.research.specification.model", "OnlyResearchSpecification"),
        }
    ),
}

EXPECTED_CLI_ONLYALPHA_IMPORTS: frozenset[CanonicalImport] = frozenset(
    {
        ("symbol", "onlyalpha.application", "OnlyEngineInspectionService"),
        ("symbol", "onlyalpha.application.engine_runner", "OnlyEngineApplicationRunner"),
        ("symbol", "onlyalpha.application.engine_runner", "OnlyRuntimeLifecycleKind"),
        ("symbol", "onlyalpha.application.engine_runner", "only_engine_lifecycle_kind"),
        ("symbol", "onlyalpha.core.errors", "OnlyError"),
        ("symbol", "onlyalpha.domain.identifiers", "OnlyEngineId"),
        ("symbol", "onlyalpha.engine", "OnlyEngine"),
        ("symbol", "onlyalpha.engine", "OnlyEngineConfig"),
        ("symbol", "onlyalpha.persistence.postgres", "OnlyPostgresConfig"),
        ("symbol", "onlyalpha.persistence.postgres", "OnlyPostgresResearchOperationsStore"),
        ("symbol", "onlyalpha.research.operations.diagnostics", "OnlyResearchOperationalDiagnosticService"),
        ("symbol", "onlyalpha.research.run", "OnlyResearchRunId"),
        ("symbol", "onlyalpha.runtime.defaults", "only_default_engine_services"),
        ("symbol", "onlyalpha.scenario", "OnlyMarketScenarioParser"),
        ("symbol", "onlyalpha.scenario", "OnlyMarketScenarioRunRequest"),
        ("symbol", "onlyalpha.scenario", "OnlyMarketScenarioRunner"),
    }
)

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


def _forbidden_capability_imports(
    source: str,
    *,
    forbidden_imports: tuple[str, ...],
    forbidden_capabilities: tuple[str, ...],
) -> frozenset[CanonicalImport]:
    return frozenset(
        capability
        for capability in onlyalpha_imports(source)
        if capability[1].startswith(forbidden_imports)
        or (len(capability) == 3 and capability[2] in forbidden_capabilities)
    )


def _assert_no_forbidden_capability(
    path: Path,
    *,
    forbidden_imports: tuple[str, ...],
    forbidden_capabilities: tuple[str, ...],
) -> None:
    violations = _forbidden_capability_imports(
        path.read_text(encoding="utf-8"),
        forbidden_imports=forbidden_imports,
        forbidden_capabilities=forbidden_capabilities,
    )
    assert not violations, f"{path.relative_to(ROOT)} obtains forbidden authorities {sorted(violations)}"


def test_api_routes_do_not_own_semantic_or_infrastructure_writers() -> None:
    route_paths = tuple(path for path in sorted(API_ROOT.rglob("*.py")) if _defines_http_route(path))
    assert {path.relative_to(ROOT).as_posix() for path in route_paths} == EXPECTED_HTTP_ROUTE_MODULES
    assert set(EXPECTED_ROUTE_ONLYALPHA_IMPORTS) == EXPECTED_HTTP_ROUTE_MODULES
    for path in route_paths:
        relative = path.relative_to(ROOT).as_posix()
        assert onlyalpha_imports(path.read_text(encoding="utf-8")) == EXPECTED_ROUTE_ONLYALPHA_IMPORTS[relative]


def test_unexpected_route_filename_is_still_detected() -> None:
    source = (
        "from onlyalpha.application.strategy_authority import OnlyStrategyPromotionApplicationService\n"
        "router = object()\n@router.post('/strategy')\ndef publish(): pass\n"
    )
    assert _source_defines_http_route(source)
    assert (
        "symbol",
        "onlyalpha.application.strategy_authority",
        "OnlyStrategyPromotionApplicationService",
    ) in onlyalpha_imports(source)
    approved = frozenset().union(*EXPECTED_ROUTE_ONLYALPHA_IMPORTS.values())
    assert onlyalpha_imports(source).isdisjoint(approved)


def test_cli_capability_set_is_frozen() -> None:
    cli = ROOT / "src/onlyalpha/cli.py"
    assert onlyalpha_imports(cli.read_text(encoding="utf-8")) == EXPECTED_CLI_ONLYALPHA_IMPORTS


def test_cli_new_strategy_mutation_capability_changes_the_frozen_set() -> None:
    source = "from onlyalpha.application.strategy_authority import OnlyStrategyPromotionApplicationService\n"
    assert onlyalpha_imports(source) != EXPECTED_CLI_ONLYALPHA_IMPORTS


def test_cli_plain_module_import_cannot_bypass_the_frozen_set() -> None:
    source = "import onlyalpha.application.strategy_authority as authority\n"
    assert onlyalpha_imports(source) == frozenset({("module", "onlyalpha.application.strategy_authority")})
    assert onlyalpha_imports(source) != EXPECTED_CLI_ONLYALPHA_IMPORTS


def test_cli_symbol_alias_preserves_original_capability_identity() -> None:
    source = (
        "from onlyalpha.application.strategy_authority import OnlyStrategyPromotionApplicationService as Promotion\n"
    )
    assert onlyalpha_imports(source) == frozenset(
        {
            (
                "symbol",
                "onlyalpha.application.strategy_authority",
                "OnlyStrategyPromotionApplicationService",
            )
        }
    )


def test_research_worker_remains_execution_agent_without_strategy_product_authority() -> None:
    paths = (ROOT / "src/onlyalpha/research/worker_main.py", *sorted(RESEARCH_EXECUTION_ROOT.rglob("*.py")))
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
    assert _forbidden_capability_imports(
        source,
        forbidden_imports=FORBIDDEN_WORKER_IMPORTS,
        forbidden_capabilities=FORBIDDEN_WORKER_CAPABILITIES,
    ) == frozenset(
        {
            (
                "symbol",
                "onlyalpha.application.strategy_authority",
                "OnlyStrategyPromotionApplicationService",
            )
        }
    )


def test_nested_research_execution_module_is_in_the_recursive_guard(tmp_path: Path) -> None:
    execution_root = tmp_path / "research/execution"
    nested = execution_root / "nested/foo.py"
    nested.parent.mkdir(parents=True)
    nested.write_text(
        "from onlyalpha.application.strategy_authority import OnlyStrategyPromotionApplicationService\n",
        encoding="utf-8",
    )
    paths = tuple(sorted(execution_root.rglob("*.py")))
    assert paths == (nested,)
    assert _forbidden_capability_imports(
        nested.read_text(encoding="utf-8"),
        forbidden_imports=FORBIDDEN_WORKER_IMPORTS,
        forbidden_capabilities=FORBIDDEN_WORKER_CAPABILITIES,
    )


def test_projection_reconciliation_is_operator_infrastructure_only() -> None:
    report = (ROOT / "docs/reports/p9_k0_product_surface_inventory.md").read_text(encoding="utf-8")
    row = next(line for line in report.splitlines() if line.startswith("| K0-S022 |"))
    assert "OPERATOR / INFRASTRUCTURE ONLY" in row
    assert "`KEEP INTERNAL`" not in row


def test_k01_closure_evidence_is_bound_to_the_immutable_subject() -> None:
    report = (ROOT / "docs/reports/p9_k0_product_surface_inventory.md").read_text(encoding="utf-8")
    assert "K0.1 implementation subject: `aeced4b4e198ed2c3035eea5ab04a46785b00a26`" in report
    assert "Closure SHA: `WORKTREE`" not in report


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
