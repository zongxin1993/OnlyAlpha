"""Default smallest-period primary via HistoricalReplayService."""

from examples.event_market_data_demo.common import run_minutes
from examples.integration_demo.environment import OnlyIntegrationEnvironment


def main() -> None:
    env = OnlyIntegrationEnvironment()
    run_minutes(env)
    assert len(env.cluster.snapshots) == 3


if __name__ == "__main__":
    main()
