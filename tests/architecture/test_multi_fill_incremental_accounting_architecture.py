import ast
from pathlib import Path

from onlyalpha.execution import (
    OnlyCommittedRuntimeTransaction,
    OnlyPreparedRuntimeTransaction,
    OnlyRuntimeProjectionComponent,
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    }


def test_multi_fill_reducers_remain_pure_and_authorities_stay_separate() -> None:
    reducer_paths = tuple(Path("src/onlyalpha/execution/reducers").glob("trade_*.py"))
    for path in reducer_paths:
        imports = _imports(path)
        assert not any("manager" in item or "store" in item or "event.bus" in item for item in imports), path
    fee_manager = Path("src/onlyalpha/fee/manager.py").read_text(encoding="utf-8")
    accrual_manager = Path("src/onlyalpha/fee/accrual_manager.py").read_text(encoding="utf-8")
    order = Path("src/onlyalpha/order/entities.py").read_text(encoding="utf-8")
    assert "OnlyFeeRateRule" not in fee_manager and "OnlyFeeEngine" not in fee_manager
    assert "Schedule" not in accrual_manager and "OnlyFeeRateRule" not in accrual_manager
    assert "FeeAccrual" not in order
    assert OnlyRuntimeProjectionComponent.ORDER_FEE_ACCRUAL.value == "ORDER_FEE_ACCRUAL"


def test_accounting_uses_explicit_deltas_and_order_terminal_authority() -> None:
    accounting = Path("src/onlyalpha/execution/reducers/trade_accounting.py").read_text(encoding="utf-8")
    reservations = Path("src/onlyalpha/execution/reducers/trade_reservations.py").read_text(encoding="utf-8")
    state = Path("src/onlyalpha/execution/reducers/trade_state.py").read_text(encoding="utf-8")
    planner = Path("src/onlyalpha/execution/trade_planner.py").read_text(encoding="utf-8")
    assert accounting.count("reservation_reduction.consumed_delta") >= 2
    assert accounting.count("reservation_reduction.released_delta") >= 2
    assert "terminal_fill" in reservations
    assert "terminal_fill" in planner and "order.terminal_fill" in planner
    assert "average_open_price.value *" not in state
    assert "PARTIAL_FILL_ACCOUNTING_NOT_READY" not in planner


def test_transaction_contracts_stay_immutable_and_scope_exclusions_remain() -> None:
    assert OnlyPreparedRuntimeTransaction.__dataclass_params__.frozen
    assert OnlyCommittedRuntimeTransaction.__dataclass_params__.frozen
    planner = Path("src/onlyalpha/execution/trade_planner.py").read_text(encoding="utf-8")
    runtime = Path("src/onlyalpha/runtime/backtest/runtime.py").read_text(encoding="utf-8")
    combined = planner + runtime
    for excluded in ("partial_fill_schedule", "fault_switch", "fault_injection"):
        assert excluded not in combined.lower()
