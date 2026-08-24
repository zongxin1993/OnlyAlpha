from onlyalpha.config import OnlyClusterRunConfig

from ..runtime_runner import only_run_cluster_runtime


def test_product_cluster_runs_only_the_revision_backed_strategy_projection() -> None:
    result = only_run_cluster_runtime(OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json"))
    cluster = result.cluster_results[0]
    extension = cluster.strategy_result_extension
    assert len(extension["strategy_fingerprint"]) == 64
    assert extension["last_strategy_decision"] is not None
    assert not cluster.factor_results
    assert not cluster.indicator_diagnostics
