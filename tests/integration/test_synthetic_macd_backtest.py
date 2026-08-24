from pathlib import Path

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.runtime.backtest.result import OnlyBacktestStatus

from ..runtime_runner import only_run_cluster_runtime

CONFIG = Path("tests/fixtures/legacy_macd/cluster.json")


def test_synthetic_macd_full_product_vertical_slice() -> None:
    result = only_run_cluster_runtime(OnlyClusterRunConfig.load(CONFIG))
    assert result.status is OnlyBacktestStatus.COMPLETED
    assert result.data.generated_bar_count == 720
    assert result.data.processed_bar_count == 720
    assert result.execution.order_count == 0
    assert result.execution.trade_count == 0
    assert not result.orders
    assert not result.final_positions
    assert not result.final_allocations
    assert result.runtime_performance.final_equity.amount == result.final_account.equity.amount
    assert all(item.endswith(":PASS") for item in result.invariant_results)


def test_synthetic_revision_emits_a_provider_neutral_final_decision() -> None:
    result = only_run_cluster_runtime(OnlyClusterRunConfig.load(CONFIG))
    decision = result.cluster_results[0].strategy_result_extension["last_strategy_decision"]
    assert isinstance(decision, dict)
    assert set(decision) >= {"eligibility", "entry", "exit", "observation_fingerprint"}
    assert not {"order_side", "quantity", "price", "broker", "account"} & set(decision)
