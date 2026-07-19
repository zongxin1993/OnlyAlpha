from typing import cast

from onlyalpha.analytics import OnlyBacktestAnalyticsService
from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.runtime.backtest.result import OnlyBacktestResult

from ..runtime_runner import only_run_cluster_runtime


def test_analytics_consumes_formal_result_without_changing_it() -> None:
    config = OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json")
    result = cast(OnlyBacktestResult, only_run_cluster_runtime(config))
    before = result.to_dict()

    first = OnlyBacktestAnalyticsService().analyze(result)
    second = OnlyBacktestAnalyticsService().analyze(result)

    assert result.to_dict() == before
    assert first == second
    assert first.analysis_fingerprint == second.analysis_fingerprint
    assert first.orders.submitted_count == 2
    assert first.orders.filled_count == 2
    assert first.executions.execution_count == 2
    assert first.trades.trade_count == 1
    assert first.trades.trades[0].entry_execution_id != first.trades.trades[0].exit_execution_id
    assert first.performance.ending_equity == result.performance.final_equity.amount
    assert "INSUFFICIENT_EQUITY_CURVE" in first.warnings
