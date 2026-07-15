"""Two Clusters sharing the Runtime-owned Aggregator through formal Replay."""

from examples.event_market_data_demo.common import run_minutes
from examples.integration_demo.environment import OnlyIntegrationCluster, OnlyIntegrationEnvironment
from onlyalpha.domain.identifiers import OnlyClusterId


def main() -> None:
    env = OnlyIntegrationEnvironment()
    second = OnlyIntegrationCluster(
        (env.bar_1m, env.bar_3m),
        OnlyClusterId("integration-cluster-b"),
        env.bar_3m,
    )
    env.runtime.add_cluster(env.runtime.config.engine_id, second)
    run_minutes(env)
    assert len(env.cluster.snapshots) == 3
    assert len(second.snapshots) == 1
    assert env.runtime.market_data_pipeline.aggregation_manager.aggregator_count == 1


if __name__ == "__main__":
    main()
