from pathlib import Path
from tempfile import TemporaryDirectory

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from tests.runtime_runner import only_migrate_cluster_to_strategy

from ..environment import OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    with TemporaryDirectory(prefix="onlyalpha-vertical-slice-") as directory:
        root = Path(directory)
        engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("vertical-slice"), root))
        engine.add_cluster(
            only_migrate_cluster_to_strategy(
                OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json"),
                root,
            )
        )
        result = engine.run()
    assert result.status == "COMPLETED"
    projection = result.cluster_results[0]
    assert projection["execution"] == {"order_count": 0, "rejected_order_count": 0, "trade_count": 0}
    cluster_results = projection["cluster_results"]
    assert isinstance(cluster_results, list)
    strategy = cluster_results[0]["strategy_result_extension"]
    assert len(strategy["strategy_fingerprint"]) == 64
    assert strategy["last_strategy_decision"] is not None
    env.product_backtest_fingerprint = result.determinism_fingerprint
    return env.report_builder.scenario(
        "034",
        "Strategy Revision Product Backtest",
        "Engine → Strategy Resolver → Cluster → Runtime → Replay → StrategyDecision → user_data",
    )
