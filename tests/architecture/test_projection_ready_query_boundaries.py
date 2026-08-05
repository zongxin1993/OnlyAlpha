import ast
import inspect
from pathlib import Path

from onlyalpha.execution import OnlyProjectionReadyRuntimeQueryPort


def _calls(path: str) -> set[str]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    return {
        node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def test_business_result_chain_uses_only_projection_ready_query() -> None:
    for path in (
        "src/onlyalpha/collector/backtest.py",
        "src/onlyalpha/runtime/backtest/run_plan.py",
    ):
        calls = _calls(path)
        assert "ready_records" in calls
        source = Path(path).read_text(encoding="utf-8")
        assert "execution_transaction_query.records" not in source
        assert "committed_execution_query" not in source
    downstream = "\n".join(
        path.read_text(encoding="utf-8")
        for root in ("analytics", "artifact", "report", "scenario")
        for path in Path(f"src/onlyalpha/{root}").rglob("*.py")
    )
    assert ".records(" not in downstream
    assert "OnlyRuntimeTransactionQueryPort" not in downstream


def test_ready_query_signature_has_no_ambiguous_filter_switch() -> None:
    ready = inspect.signature(OnlyProjectionReadyRuntimeQueryPort.ready_records)
    assert tuple(ready.parameters) == ("self", "runtime_id", "after_sequence")
    assert "ready_only" not in ready.parameters
    production = "\n".join(path.read_text(encoding="utf-8") for path in Path("src/onlyalpha").rglob("*.py"))
    assert "ready_only" not in production
    assert "committed_execution_query" not in production


def test_sqlite_ready_query_filters_in_sql() -> None:
    source = Path("src/onlyalpha/runtime/persistence/store.py").read_text(encoding="utf-8")
    assert "projection_ready=1 AND execution_sequence>?" in source
