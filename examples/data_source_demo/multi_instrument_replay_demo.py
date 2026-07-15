from dataclasses import replace

from examples.data_source_demo.common import make_update
from examples.integration_demo.environment import OnlyIntegrationEnvironment
from onlyalpha.data.identifiers import OnlyMarketDataSourceId
from onlyalpha.data.models import OnlyHistoricalDataStream, OnlyHistoricalReplayConfig
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlySymbol


def main() -> None:
    env = OnlyIntegrationEnvironment()
    source_id = OnlyMarketDataSourceId("demo-multi")
    first = make_update(env, source_id, 0, 1)
    second_id = OnlyInstrumentId(OnlySymbol("600001"), first.instrument_id.venue)
    second_bar_type = replace(first.payload.bar.bar_type, instrument_id=second_id)  # type: ignore[union-attr]
    second_bar = replace(first.payload.bar, bar_type=second_bar_type)  # type: ignore[union-attr]
    second = replace(
        first,
        update_id=type(first.update_id)("demo-multi-2"),
        instrument_id=second_id,
        payload=type(first.payload)(second_bar),
    )
    cursor = env.historical_replay_service.prepare(
        OnlyHistoricalReplayConfig((OnlyHistoricalDataStream((second, first), 2),), source_priority=(source_id,))
    )
    assert tuple(str(item.instrument_id) for item in cursor.updates) == tuple(
        sorted((str(first.instrument_id), str(second.instrument_id)))
    )


if __name__ == "__main__":
    main()
