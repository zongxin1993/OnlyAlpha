from examples.integration_demo.environment import INSTRUMENT_ID, OnlyIntegrationEnvironment
from onlyalpha.data.enums import OnlyMarketDataProcessingStatus, OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataSequence, OnlyDataVersion, OnlyMarketDataUpdateId
from onlyalpha.data.models import OnlyInstrumentStatusUpdate, OnlyMarketDataInboundUpdate
from onlyalpha.domain.time import OnlyTimestamp


def main() -> None:
    env = OnlyIntegrationEnvironment()
    env.start()
    now = OnlyTimestamp.from_unix_nanos(env.runtime.clock.timestamp_ns())
    update = OnlyMarketDataInboundUpdate(
        OnlyMarketDataUpdateId("demo-live-status"),
        env.runtime.config.runtime_id,  # type: ignore[arg-type]
        env.market_data_gateway.source_id,
        OnlyDataSequence(1),
        OnlyDataVersion("live-v1"),
        INSTRUMENT_ID,
        OnlyMarketDataType.INSTRUMENT_STATUS,
        OnlyInstrumentStatusUpdate(INSTRUMENT_ID, "OPEN"),
        now,
        now,
    )
    env.market_data_gateway.publish(update)
    assert env.runtime.drain_market_data_inbound()[0].status is OnlyMarketDataProcessingStatus.IGNORED


if __name__ == "__main__":
    main()
