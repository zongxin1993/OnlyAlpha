"""Explicit 3m primary via HistoricalReplayService."""

from examples.event_market_data_demo.common import run_minutes
from examples.integration_demo.environment import OnlyIntegrationCluster, OnlyIntegrationEnvironment
from onlyalpha.domain.identifiers import OnlyClusterId


def main() -> None:
    env = OnlyIntegrationEnvironment()
    cluster = OnlyIntegrationCluster(
        (env.bar_1m, env.bar_3m),
        OnlyClusterId("primary-3m-cluster"),
        primary_bar_type=env.bar_3m,
    )
    env.runtime.add_cluster(env.runtime.config.engine_id, cluster)
    run_minutes(env)
    assert len(cluster.snapshots) == 1


if __name__ == "__main__":
    main()
