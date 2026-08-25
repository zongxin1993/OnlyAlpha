"""Freeze P9.K.0 publication, execution-agent, and route ownership boundaries."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).parents[2]
API_RESEARCH = ROOT / "packages/api/onlyalpha-api/src/onlyalpha_api/research"

FORBIDDEN_ROUTE_IMPORTS = (
    "onlyalpha.application.strategy_authority",
    "onlyalpha.engine",
    "onlyalpha.persistence",
    "onlyalpha.runtime",
    "onlyalpha.strategy.freeze",
    "onlyalpha.strategy.promotion",
    "onlyalpha.strategy.store",
    "onlyalpha.research.execution",
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


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            result.append(node.module)
    return tuple(result)


def test_api_routes_do_not_own_semantic_or_infrastructure_writers() -> None:
    route_paths = tuple(sorted(API_RESEARCH.glob("*_routes.py"))) + (API_RESEARCH / "routes.py",)
    for path in route_paths:
        imports = _imports(path)
        for imported in imports:
            assert not imported.startswith(FORBIDDEN_ROUTE_IMPORTS), (
                f"{path.relative_to(ROOT)} imports forbidden authority {imported}"
            )
        source = path.read_text(encoding="utf-8")
        for capability in FORBIDDEN_ROUTE_CAPABILITIES:
            assert capability not in source, f"{path.relative_to(ROOT)} obtains {capability}"


def test_research_worker_remains_execution_agent_without_strategy_product_authority() -> None:
    paths = (
        ROOT / "src/onlyalpha/research/worker_main.py",
        ROOT / "src/onlyalpha/research/execution/worker.py",
    )
    forbidden_imports = (
        "onlyalpha.application.strategy_authority",
        "onlyalpha.strategy.freeze",
        "onlyalpha.strategy.promotion",
        "onlyalpha.persistence.postgres.strategy_store",
    )
    forbidden_capabilities = (
        "OnlyStrategyFreezeApplicationService",
        "OnlyStrategyPromotionApplicationService",
        "OnlyStrategyFreezeService",
        "OnlyStrategyPromotionService",
        "_OnlyFrozenStrategyPublisher",
        "_only_compose_frozen_strategy_authority",
    )
    for path in paths:
        imports = _imports(path)
        assert all(not imported.startswith(forbidden_imports) for imported in imports), path
        source = path.read_text(encoding="utf-8")
        assert all(capability not in source for capability in forbidden_capabilities), path


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
