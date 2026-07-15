from examples.data_source_demo.common import make_update, request
from examples.integration_demo.environment import OnlyIntegrationEnvironment
from onlyalpha.data.identifiers import OnlyMarketDataSourceId
from onlyalpha.data.sources import OnlyInMemoryHistoricalDataSource


def main() -> None:
    env = OnlyIntegrationEnvironment()
    env.start()
    source_id = OnlyMarketDataSourceId("demo-memory")
    source = OnlyInMemoryHistoricalDataSource(source_id, tuple(make_update(env, source_id, i, i + 1) for i in range(3)))
    assert env.runtime.replay_historical_bars(source, request(env)).applied == 3


if __name__ == "__main__":
    main()
