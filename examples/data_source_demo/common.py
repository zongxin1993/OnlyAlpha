from datetime import UTC, datetime, time, timedelta

from examples.integration_demo.environment import DAY_ONE, INSTRUMENT_ID, OnlyIntegrationEnvironment
from onlyalpha.data.enums import OnlyMarketDataQualityFlag, OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataSequence, OnlyDataVersion, OnlyMarketDataSourceId, OnlyMarketDataUpdateId
from onlyalpha.data.models import (
    OnlyBarUpdate,
    OnlyHistoricalBarRequest,
    OnlyHistoricalDataRange,
    OnlyMarketDataInboundUpdate,
    OnlyMarketDataQuality,
)
from onlyalpha.domain.time import OnlyTimestamp


def make_update(
    env: OnlyIntegrationEnvironment,
    source_id: OnlyMarketDataSourceId,
    minute: int,
    sequence: int,
) -> OnlyMarketDataInboundUpdate:
    bar = env.make_bar(DAY_ONE, minute, "10.00")
    return OnlyMarketDataInboundUpdate(
        OnlyMarketDataUpdateId(f"demo-{source_id}-{sequence}"),
        env.runtime.config.runtime_id,  # type: ignore[arg-type]
        source_id,
        OnlyDataSequence(sequence),
        OnlyDataVersion("demo-v1"),
        INSTRUMENT_ID,
        OnlyMarketDataType.BAR,
        OnlyBarUpdate(bar),
        OnlyTimestamp.from_datetime(bar.ts_event),
        OnlyTimestamp.from_datetime(bar.ts_init),
        OnlyMarketDataQuality(frozenset({OnlyMarketDataQualityFlag.UNADJUSTED})),
    )


def request(env: OnlyIntegrationEnvironment) -> OnlyHistoricalBarRequest:
    start = datetime.combine(DAY_ONE, time(1, 30), tzinfo=UTC)
    return OnlyHistoricalBarRequest(
        "demo-request",
        frozenset({INSTRUMENT_ID}),
        frozenset({env.bar_1m}),
        OnlyHistoricalDataRange(start, start + timedelta(minutes=10)),
        OnlyDataVersion("demo-v1"),
    )
