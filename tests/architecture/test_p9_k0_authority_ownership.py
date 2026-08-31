"""Freeze P9.K.0 publication, execution-agent, and route ownership boundaries."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.architecture._p9_k0_guard_helpers import (
    CanonicalImport,
    onlyalpha_imports,
    onlyalpha_imports_for_path,
)

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
            ("symbol", "onlyalpha.application.product_boundary", "OnlyCancelResearchRun"),
            ("symbol", "onlyalpha.application.product_boundary", "OnlyCreateResearchRun"),
            ("symbol", "onlyalpha.application.product_boundary", "OnlyGetResearchRun"),
            ("symbol", "onlyalpha.application.product_boundary", "OnlyListResearchRuns"),
            ("symbol", "onlyalpha.application.product_boundary", "OnlyResearchProductBoundary"),
            ("symbol", "onlyalpha.research.command.errors", "OnlyResearchCommandError"),
            ("symbol", "onlyalpha.research.command.errors", "OnlyResearchCommandPhase"),
            ("symbol", "onlyalpha.research.command.model", "OnlyResearchRunPage"),
            ("symbol", "onlyalpha.research.command.model", "OnlyResearchSubmissionKey"),
            ("symbol", "onlyalpha.research.command.model", "OnlyResearchSubmitOutcome"),
            ("symbol", "onlyalpha.research.command.query", "DEFAULT_RESEARCH_RUN_PAGE_SIZE"),
            ("symbol", "onlyalpha.research.run.model", "OnlyResearchRun"),
            ("symbol", "onlyalpha.research.run.model", "OnlyResearchRunId"),
            ("symbol", "onlyalpha.research.specification.model", "OnlyResearchSpecification"),
        }
    ),
}

EXPECTED_CLI_ONLYALPHA_IMPORTS: frozenset[CanonicalImport] = frozenset(
    {
        ("symbol", "onlyalpha.core.errors", "OnlyError"),
        ("symbol", "onlyalpha.persistence.postgres", "OnlyPostgresConfig"),
        ("symbol", "onlyalpha.persistence.postgres", "OnlyPostgresResearchOperationsStore"),
        ("symbol", "onlyalpha.research.operations.diagnostics", "OnlyResearchOperationalDiagnosticService"),
        ("symbol", "onlyalpha.research.run", "OnlyResearchRunId"),
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
FORBIDDEN_WORKER_AGGREGATORS = ("onlyalpha.application",)
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
        if any(capability[1] == imported or capability[1].startswith(f"{imported}.") for imported in forbidden_imports)
        or capability[1] in FORBIDDEN_WORKER_AGGREGATORS
        or (len(capability) == 3 and capability[2] in forbidden_capabilities)
    )


def _assert_no_forbidden_capability(
    path: Path,
    *,
    forbidden_imports: tuple[str, ...],
    forbidden_capabilities: tuple[str, ...],
) -> None:
    imports = onlyalpha_imports_for_path(path, ROOT)
    violations = frozenset(
        capability
        for capability in imports
        if any(capability[1] == imported or capability[1].startswith(f"{imported}.") for imported in forbidden_imports)
        or capability[1] in FORBIDDEN_WORKER_AGGREGATORS
        or (len(capability) == 3 and capability[2] in forbidden_capabilities)
    )
    assert not violations, f"{path.relative_to(ROOT)} obtains forbidden authorities {sorted(violations)}"


def test_api_routes_do_not_own_semantic_or_infrastructure_writers() -> None:
    route_paths = tuple(path for path in sorted(API_ROOT.rglob("*.py")) if _defines_http_route(path))
    assert {path.relative_to(ROOT).as_posix() for path in route_paths} == EXPECTED_HTTP_ROUTE_MODULES
    assert set(EXPECTED_ROUTE_ONLYALPHA_IMPORTS) == EXPECTED_HTTP_ROUTE_MODULES
    for path in route_paths:
        relative = path.relative_to(ROOT).as_posix()
        assert onlyalpha_imports_for_path(path, ROOT) == EXPECTED_ROUTE_ONLYALPHA_IMPORTS[relative]


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
    assert onlyalpha_imports_for_path(cli, ROOT) == EXPECTED_CLI_ONLYALPHA_IMPORTS


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


def test_worker_direct_strategy_freeze_capability_is_forbidden() -> None:
    source = "from onlyalpha.strategy.freeze import OnlyStrategyFreezeService\n"
    assert _forbidden_capability_imports(
        source,
        forbidden_imports=FORBIDDEN_WORKER_IMPORTS,
        forbidden_capabilities=FORBIDDEN_WORKER_CAPABILITIES,
    )


def test_worker_broad_application_aggregator_is_forbidden() -> None:
    source = "import onlyalpha.application as app\n"
    assert _forbidden_capability_imports(
        source,
        forbidden_imports=FORBIDDEN_WORKER_IMPORTS,
        forbidden_capabilities=FORBIDDEN_WORKER_CAPABILITIES,
    ) == frozenset({("module", "onlyalpha.application")})


def test_worker_future_kernel_import_is_forbidden() -> None:
    source = "import onlyalpha.kernel\n"
    assert _forbidden_capability_imports(
        source,
        forbidden_imports=FORBIDDEN_WORKER_IMPORTS,
        forbidden_capabilities=FORBIDDEN_WORKER_CAPABILITIES,
    ) == frozenset({("module", "onlyalpha.kernel")})


def test_worker_relative_alias_resolves_to_same_strategy_authority(tmp_path: Path) -> None:
    root = tmp_path
    worker = root / "src/onlyalpha/research/execution/worker.py"
    worker.parent.mkdir(parents=True)
    worker.write_text(
        "from ...application import OnlyStrategyPromotionApplicationService as Promotion\n",
        encoding="utf-8",
    )
    assert onlyalpha_imports_for_path(worker, root) == frozenset(
        {
            (
                "symbol",
                "onlyalpha.application",
                "OnlyStrategyPromotionApplicationService",
            )
        }
    )


@pytest.mark.parametrize(
    ("relative_path", "statement"),
    (
        ("src/onlyalpha/worker.py", "from .application import Capability\n"),
        ("src/onlyalpha/research/worker.py", "from ..application import Capability\n"),
        (
            "src/onlyalpha/research/execution/worker.py",
            "from ...application import Capability\n",
        ),
        (
            "src/onlyalpha/research/execution/nested/worker.py",
            "from ....application import Capability\n",
        ),
    ),
)
def test_relative_import_depth_has_one_canonical_authority(relative_path: str, statement: str, tmp_path: Path) -> None:
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True)
    path.write_text(statement, encoding="utf-8")
    assert onlyalpha_imports_for_path(path, tmp_path) == frozenset({("symbol", "onlyalpha.application", "Capability")})


def test_guarded_relative_import_without_module_identity_fails_closed(tmp_path: Path) -> None:
    worker = tmp_path / "worker.py"
    worker.write_text("from .application import Capability\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot resolve relative import module"):
        onlyalpha_imports_for_path(worker, tmp_path)


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
    assert not (ROOT / "docs/reports/p9_k0_product_surface_inventory.md").exists()
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "仓库不得把以下内容作为当前 Authority" in agents
    assert "质量/审计/验收/closure 报告" in agents


def test_k01_closure_evidence_is_bound_to_the_immutable_subject() -> None:
    assert not (ROOT / "docs/reports/p9_k0_product_surface_inventory.md").exists()
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "Final-SHA / Exact-SHA 工程认证记录" in agents


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
