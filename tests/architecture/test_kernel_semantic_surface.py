"""Permanent guards for the graduated canonical Kernel surface."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scripts.audit_src_semantic_surface import collect

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).parents[2]
SOURCE_ROOT = ROOT / "src" / "onlyalpha"

REMOVED_SYMBOLS = frozenset(
    {
        "OnlyRuntimeServices",
        "OnlyRuntimeContextView",
        "OnlyClusterContext",
        "OnlyBrokerFactory",
        "OnlyCancelRequest",
        "OnlyAccountBalance",
        "OnlyHistoricalCacheKey",
        "OnlyResearchSubmissionKey",
        "OnlyResearchDatasetSourceContract",
        "OnlyAgentEvaluationContextReferenceV1",
        "OnlyIndicatorDefinition",
        "OnlyFactorDefinition",
        "OnlyOrderQueryView",
        "OnlyOrderContextView",
        "OnlyPositionQueryView",
        "OnlyPositionAllocationQueryView",
        "OnlyPositionAllocation",
        "OnlyPositionFill",
        "OnlyAccountPositionRiskViewAlias",
        "OnlyClusterPositionRiskViewAlias",
    }
)


def _trees() -> tuple[tuple[Path, ast.Module], ...]:
    return tuple(
        (path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        for path in sorted(SOURCE_ROOT.rglob("*.py"))
    )


def test_every_src_module_has_an_explicit_inventory_classification() -> None:
    records = collect()
    assert len(records) == len(tuple(SOURCE_ROOT.rglob("*.py")))
    assert {record.classification for record in records} <= {"CANONICAL", "EXTERNAL_ADAPTER"}
    assert all(record.path.is_file() for record in records)


def test_removed_compatibility_symbols_and_reexport_modules_stay_absent() -> None:
    assert not (SOURCE_ROOT / "runtime" / "research" / "errors.py").exists()
    assert not (SOURCE_ROOT / "runtime" / "research" / "plan.py").exists()
    assert not (SOURCE_ROOT / "research" / "definition" / "primitives.py").exists()
    for path, tree in _trees():
        symbols = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assigned = {
            target.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        assert not symbols.intersection(REMOVED_SYMBOLS), path
        assert not assigned.intersection(REMOVED_SYMBOLS), path


def test_kernel_has_no_direct_compatibility_alias_assignments() -> None:
    for path, tree in _trees():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name) or not target.id.startswith("Only"):
                continue
            assert not isinstance(node.value, (ast.Name, ast.Attribute)), f"{path}:{node.lineno}"


def test_factory_registries_have_one_resolution_entrypoint() -> None:
    for relative in ("data/factory.py", "broker/factory.py"):
        tree = ast.parse((SOURCE_ROOT / relative).read_text(encoding="utf-8"))
        assert not any(isinstance(node, ast.FunctionDef) and node.name == "require" for node in ast.walk(tree))
        assert sum(isinstance(node, ast.FunctionDef) and node.name == "resolve" for node in ast.walk(tree)) == 1


@pytest.mark.parametrize(
    ("source", "test"),
    (
        ("src/onlyalpha/core/clock.py", "tests/clock/test_clock_event.py"),
        ("src/onlyalpha/domain/calendar.py", "tests/time_model/test_04_trading_calendar.py"),
        ("src/onlyalpha/runtime/context.py", "tests/architecture/test_committed_execution_boundaries.py"),
        (
            "src/onlyalpha/runtime/trading/services.py",
            "tests/architecture/test_execution_runtime_recovery_boundaries.py",
        ),
        ("src/onlyalpha/research/calculation/binding.py", "tests/research/calculation/test_predicate_primitives.py"),
        ("src/onlyalpha/research/command/model.py", "tests/research/command/test_service.py"),
    ),
)
def test_graduated_semantic_units_have_direct_test_ownership(source: str, test: str) -> None:
    assert (ROOT / source).is_file()
    assert (ROOT / test).is_file()
