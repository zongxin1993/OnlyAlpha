import ast
from pathlib import Path

ROOT = Path("src/onlyalpha")


def _trees() -> tuple[tuple[Path, ast.AST], ...]:
    return tuple((path, ast.parse(path.read_text(encoding="utf-8"))) for path in ROOT.rglob("*.py"))


def test_production_code_never_selects_first_strategy_ledger() -> None:
    violations: list[str] = []
    for path, tree in _trees():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Subscript):
                continue
            zero = isinstance(node.slice, ast.Constant) and node.slice.value == 0
            if not zero:
                continue
            if isinstance(node.value, ast.Name) and node.value.id == "ledgers":
                violations.append(f"{path}:{node.lineno}:ledgers[0]")
            if (
                isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr == "list_ledgers"
            ):
                violations.append(f"{path}:{node.lineno}:list_ledgers()[0]")
    assert violations == []


def test_execution_and_result_use_formal_authority_boundaries() -> None:
    execution = ast.parse(Path("src/onlyalpha/execution/processor.py").read_text(encoding="utf-8"))
    execution_calls = {
        node.func.id for node in ast.walk(execution) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "OnlyStrategyLedgerKey" not in execution_calls

    run_plan = Path("src/onlyalpha/runtime/backtest/run_plan.py").read_text(encoding="utf-8")
    assert "account_performance_projector.summarize" in run_plan
    assert "OnlyRuntimePortfolioPerformanceSummary(" not in run_plan
    assert "zip(self._clusters" not in run_plan

    result_model = Path("src/onlyalpha/runtime/backtest/result.py").read_text(encoding="utf-8")
    assert "runtime_performance: OnlyRuntimePortfolioPerformanceSummary" in result_model
    assert "performance: OnlyBacktestPerformanceSummary" not in result_model
