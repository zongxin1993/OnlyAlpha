"""Past-fact market-data and replay event records."""

from dataclasses import dataclass

from onlyalpha.data.identifiers import OnlyMarketDataSourceId, OnlyMarketDataUpdateId
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp


@dataclass(frozen=True, slots=True)
class OnlyMarketDataFactEvent:
    runtime_id: OnlyRuntimeId
    source_id: OnlyMarketDataSourceId
    timestamp: OnlyTimestamp
    sequence: int
    update_id: OnlyMarketDataUpdateId | None = None


class OnlyMarketDataSourceConnectedEvent(OnlyMarketDataFactEvent):
    pass


class OnlyMarketDataSourceDisconnectedEvent(OnlyMarketDataFactEvent):
    pass


class OnlyMarketDataSubscribedEvent(OnlyMarketDataFactEvent):
    pass


class OnlyMarketDataUnsubscribedEvent(OnlyMarketDataFactEvent):
    pass


class OnlyMarketDataReceivedEvent(OnlyMarketDataFactEvent):
    pass


class OnlyMarketDataAppliedEvent(OnlyMarketDataFactEvent):
    pass


class OnlyMarketDataDuplicateEvent(OnlyMarketDataFactEvent):
    pass


class OnlyMarketDataStaleEvent(OnlyMarketDataFactEvent):
    pass


class OnlyMarketDataGapDetectedEvent(OnlyMarketDataFactEvent):
    pass


class OnlyMarketDataRejectedEvent(OnlyMarketDataFactEvent):
    pass


class OnlyHistoricalReplayStartedEvent(OnlyMarketDataFactEvent):
    pass


class OnlyHistoricalReplayPausedEvent(OnlyMarketDataFactEvent):
    pass


class OnlyHistoricalReplayCompletedEvent(OnlyMarketDataFactEvent):
    pass


class OnlyHistoricalReplayFailedEvent(OnlyMarketDataFactEvent):
    pass
