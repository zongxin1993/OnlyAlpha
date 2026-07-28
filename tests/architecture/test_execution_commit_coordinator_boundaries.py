import ast
import inspect
from pathlib import Path

from onlyalpha.execution import OnlyExecutionCommitCoordinator


def _imports(path: str) -> set[str]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    return {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names} | {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }


def test_coordinator_planner_and_store_dependency_direction() -> None:
    coordinator = _imports("src/onlyalpha/execution/commit_coordinator.py")
    planner = _imports("src/onlyalpha/execution/trade_planner.py")
    store = _imports("src/onlyalpha/execution/transaction_store.py")
    assert not any(name.endswith(".manager") for name in coordinator)
    assert not any(
        name.endswith(".manager") or ".runtime" in name or name.endswith("transaction_store") for name in planner
    )
    assert "onlyalpha.event.bus" not in planner
    assert not any(name.endswith(".manager") or ".runtime" in name for name in store)


def test_projection_targets_use_restore_authority_not_business_mutations() -> None:
    source = Path("src/onlyalpha/execution/projection_targets.py").read_text(encoding="utf-8")
    for forbidden in (
        ".apply_fill(",
        ".apply_trade(",
        ".apply_trade_accounting(",
        ".apply_trade_cash_flow(",
        ".consume_order_fill(",
        ".submit_order(",
    ):
        assert forbidden not in source
    assert ".restore_execution_authority(" in source


def test_product_supported_trade_path_has_one_transaction_authority_and_no_switch() -> None:
    processor = Path("src/onlyalpha/execution/processor.py").read_text(encoding="utf-8")
    runtime = Path("src/onlyalpha/runtime/backtest/runtime.py").read_text(encoding="utf-8")
    execution = "\n".join(path.read_text(encoding="utf-8") for path in Path("src/onlyalpha/execution").glob("*.py"))
    assert "def _trade(" not in processor
    assert "self._execution_commit_coordinator.commit(" in processor
    assert "OnlyInMemoryExecutionTransactionStore()" in runtime
    assert "OnlyExecutionCommitCoordinator(" in runtime
    assert "CommittedExecutionJournal" not in execution
    assert "ExecutionCommitPort" not in execution
    assert "feature_flag" not in processor.lower()
    assert "legacy_" not in execution


def test_applied_ledger_is_only_an_in_memory_rebuildable_index() -> None:
    source = Path("src/onlyalpha/execution/applied_projection.py").read_text(encoding="utf-8")
    assert "class OnlyInMemoryAppliedProjectionLedger" in source
    assert "sqlite" not in source.lower()
    assert "open(" not in source


def test_coordinator_has_no_compatibility_constructor() -> None:
    parameters = inspect.signature(OnlyExecutionCommitCoordinator).parameters
    assert tuple(parameters) == (
        "commit_port",
        "query_port",
        "projection_state_port",
        "projection_applier",
        "now",
    )
    assert all(parameter.default is inspect.Parameter.empty for parameter in parameters.values())
