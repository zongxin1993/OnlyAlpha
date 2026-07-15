"""Stable multi-stream historical merge and the sole data-driven Backtest Clock owner."""

from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.data.enums import OnlyHistoricalReplayState, OnlyMarketDataProcessingStatus, OnlyMarketDataType
from onlyalpha.data.models import (
    OnlyHistoricalReplayConfig,
    OnlyHistoricalReplayCursor,
    OnlyHistoricalReplayEvent,
    OnlyHistoricalReplayResult,
    OnlyMarketDataInboundUpdate,
)
from onlyalpha.data.processor import OnlyMarketDataProcessor
from onlyalpha.market_data.subscriptions import only_bar_type_id

_DATA_TYPE_PRIORITY = {
    OnlyMarketDataType.INSTRUMENT_STATUS: 0,
    OnlyMarketDataType.QUOTE: 1,
    OnlyMarketDataType.TRADE: 2,
    OnlyMarketDataType.BAR: 3,
}


class OnlyHistoricalReplayService:
    def __init__(self, clock: OnlyBacktestClock, processor: OnlyMarketDataProcessor) -> None:
        self._clock = clock
        self._processor = processor
        self._events: list[OnlyHistoricalReplayEvent] = []

    def prepare(self, config: OnlyHistoricalReplayConfig) -> OnlyHistoricalReplayCursor:
        source_priority = {source_id: index for index, source_id in enumerate(config.source_priority)}

        def key(update: OnlyMarketDataInboundUpdate) -> tuple[object, ...]:
            return (
                update.ts_event.unix_nanos,
                _DATA_TYPE_PRIORITY[update.data_type],
                str(update.instrument_id),
                "" if update.bar_type is None else only_bar_type_id(update.bar_type),
                source_priority.get(update.source_id, len(source_priority)),
                int(update.source_sequence),
                str(update.update_id),
            )

        return OnlyHistoricalReplayCursor(
            tuple(sorted((item for stream in config.streams for item in stream), key=key))
        )

    def step(self, cursor: OnlyHistoricalReplayCursor) -> OnlyHistoricalReplayEvent | None:
        if cursor.state in (OnlyHistoricalReplayState.STOPPED, OnlyHistoricalReplayState.COMPLETED):
            return None
        if cursor.index >= len(cursor.updates):
            cursor.state = OnlyHistoricalReplayState.COMPLETED
            return None
        cursor.state = OnlyHistoricalReplayState.RUNNING
        update = cursor.updates[cursor.index]
        advance = self._clock.advance_to(update.ts_event.unix_nanos)
        result = self._processor.process(update)
        event = OnlyHistoricalReplayEvent(cursor.index, update, result, self._clock.timestamp_ns(), advance)
        cursor.results.append(result)
        cursor.index += 1
        self._events.append(event)
        if cursor.index >= len(cursor.updates):
            cursor.state = OnlyHistoricalReplayState.COMPLETED
        return event

    def run(self, cursor: OnlyHistoricalReplayCursor) -> OnlyHistoricalReplayResult:
        started = len(self._events)
        try:
            while cursor.state not in (OnlyHistoricalReplayState.PAUSED, OnlyHistoricalReplayState.STOPPED):
                if self.step(cursor) is None:
                    break
        except Exception:
            cursor.state = OnlyHistoricalReplayState.FAILED
            raise
        events = tuple(self._events[started:])
        statuses = tuple(event.result.status for event in events)
        return OnlyHistoricalReplayResult(
            cursor.state,
            len(events),
            statuses.count(OnlyMarketDataProcessingStatus.APPLIED),
            statuses.count(OnlyMarketDataProcessingStatus.DUPLICATE),
            statuses.count(OnlyMarketDataProcessingStatus.GAP_DETECTED),
            statuses.count(OnlyMarketDataProcessingStatus.REJECTED),
            statuses.count(OnlyMarketDataProcessingStatus.FAILED),
            events,
        )

    @staticmethod
    def pause(cursor: OnlyHistoricalReplayCursor) -> None:
        if cursor.state is OnlyHistoricalReplayState.RUNNING:
            cursor.state = OnlyHistoricalReplayState.PAUSED

    @staticmethod
    def resume(cursor: OnlyHistoricalReplayCursor) -> None:
        if cursor.state is OnlyHistoricalReplayState.PAUSED:
            cursor.state = OnlyHistoricalReplayState.RUNNING

    @staticmethod
    def stop(cursor: OnlyHistoricalReplayCursor) -> None:
        cursor.state = OnlyHistoricalReplayState.STOPPED

    @property
    def events(self) -> tuple[OnlyHistoricalReplayEvent, ...]:
        return tuple(self._events)
