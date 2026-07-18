from onlyalpha.config import OnlyClusterRunConfig

from ..runtime_runner import only_run_cluster_runtime


def test_product_cluster_runs_indicator_factor_strategy_and_waits_for_required_warmup() -> None:
    result = only_run_cluster_runtime(OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json"))
    cluster = result.cluster_results[0]
    assert cluster.strategy_result_extension["callback_count"] == 713
    assert cluster.factor_results[0]["factor_id"] == "macd-signal"
    assert cluster.factor_results[0]["ready"] is True
    assert cluster.indicator_diagnostics[0]["indicator_id"] == "macd-primary"
    assert cluster.indicator_diagnostics[0]["ready"] is True
