from pathlib import Path

from onlyalpha.config import OnlyRunConfig
from onlyalpha.domain.enums import OnlyOrderSide, OnlyOrderStatus
from onlyalpha.runtime.backtest.result import OnlyBacktestStatus
from onlyalpha.runtime.defaults import only_default_run_service

CONFIG = Path("examples/backtest_macd/config.yaml")


def test_synthetic_macd_full_product_vertical_slice() -> None:
    result = only_default_run_service().run(OnlyRunConfig.load(CONFIG), export=False)
    assert result.status is OnlyBacktestStatus.COMPLETED
    assert result.data.generated_bar_count == 720
    assert result.data.processed_bar_count == 720
    assert result.execution.order_count == 2
    assert result.execution.trade_count == 2
    assert [item.side for item in result.orders] == [OnlyOrderSide.BUY, OnlyOrderSide.SELL]
    assert all(item.status is OnlyOrderStatus.FILLED for item in result.orders)
    assert not result.final_positions
    assert not result.final_allocations
    assert result.performance.final_equity.amount == result.final_accounts[0].equity.amount
    assert all(item.endswith(":PASS") for item in result.invariant_results)


def test_synthetic_macd_t1_is_derived_from_allocation_availability() -> None:
    result = only_default_run_service().run(OnlyRunConfig.load(CONFIG), export=False)
    assert result.execution.blocked_t1_exit_count == 1
    assert [item.signal_type for item in result.signals] == [
        "GOLDEN_CROSS",
        "DEATH_CROSS_BLOCKED",
        "PENDING_EXIT",
    ]
    assert result.signals[1].ts_event.unix_nanos < result.signals[2].ts_event.unix_nanos
