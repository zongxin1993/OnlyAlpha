from pathlib import Path

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.enums import OnlyOrderSide, OnlyOrderStatus
from onlyalpha.runtime.backtest.result import OnlyBacktestStatus

from ..runtime_runner import only_run_cluster_runtime

CONFIG = Path("tests/fixtures/legacy_macd/cluster.json")


def test_synthetic_macd_full_product_vertical_slice() -> None:
    result = only_run_cluster_runtime(OnlyClusterRunConfig.load(CONFIG))
    assert result.status is OnlyBacktestStatus.COMPLETED
    assert result.data.generated_bar_count == 720
    assert result.data.processed_bar_count == 720
    assert result.execution.order_count == 2
    assert result.execution.trade_count == 2
    assert [item.side for item in result.orders] == [OnlyOrderSide.BUY, OnlyOrderSide.SELL]
    assert all(item.status is OnlyOrderStatus.FILLED for item in result.orders)
    assert not result.final_positions
    assert not result.final_allocations
    assert result.runtime_performance.final_equity.amount == result.final_account.equity.amount
    assert all(item.endswith(":PASS") for item in result.invariant_results)


def test_synthetic_macd_generic_t0_allows_same_day_available_position() -> None:
    result = only_run_cluster_runtime(OnlyClusterRunConfig.load(CONFIG))
    signals = result.cluster_results[0].strategy_result_extension["signals"]
    assert isinstance(signals, list)
    assert [item["signal_type"] for item in signals] == ["GOLDEN_CROSS", "DEATH_CROSS"]
    assert signals[0]["ts_event_ns"] < signals[1]["ts_event_ns"]
