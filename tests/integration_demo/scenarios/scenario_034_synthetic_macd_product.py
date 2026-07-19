from pathlib import Path
from tempfile import TemporaryDirectory

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig

from ..environment import OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    with TemporaryDirectory(prefix="onlyalpha-vertical-slice-") as directory:
        engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("vertical-slice"), Path(directory)))
        engine.add_cluster_from_file("tests/fixtures/legacy_macd/cluster.json")
        result = engine.run()
    assert result.status == "COMPLETED"
    projection = result.cluster_results[0]
    assert projection["execution"] == {"order_count": 2, "rejected_order_count": 0, "trade_count": 2}
    cluster_results = projection["cluster_results"]
    assert isinstance(cluster_results, list)
    signals = cluster_results[0]["strategy_result_extension"]["signals"]
    assert isinstance(signals, list)
    assert sum(item["signal_type"] == "DEATH_CROSS" for item in signals) == 1
    env.product_backtest_fingerprint = result.determinism_fingerprint
    return env.report_builder.scenario(
        "034",
        "合成 MACD Product Backtest",
        "CLI 等价入口 → Engine → Cluster → Runtime → Replay → VirtualBroker → ExecutionProcessor → user_data",
    )
