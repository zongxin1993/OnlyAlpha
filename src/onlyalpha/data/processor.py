"""Single normalized market-data update entry before the existing Pipeline."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from datetime import timedelta
from typing import cast

from onlyalpha.core.clock import OnlyClock
from onlyalpha.data.audit import OnlyMarketDataAuditRecord, OnlyMarketDataAuditStore, OnlyMarketDataEventPublisher
from onlyalpha.data.enums import OnlyMarketDataProcessingStatus, OnlyMarketDataQualityFlag, OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.data.models import (
    OnlyBarUpdate,
    OnlyMarketDataFailure,
    OnlyMarketDataInboundUpdate,
    OnlyMarketDataProcessingResult,
    OnlyMarketDataQuality,
    OnlyMarketDataValidationResult,
)
from onlyalpha.data.registry import OnlyMarketDataSourceRegistry
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.market_data.dispatcher import OnlyBarDispatchResult, OnlyStrategyBarDispatcher
from onlyalpha.market_data.pipeline import OnlyMarketDataPipeline, OnlyMarketDataUpdateResult


class OnlyMarketDataDeduplicator:
    def __init__(self) -> None:
        self._keys: set[tuple[object, ...]] = set()

    def seen(self, update: OnlyMarketDataInboundUpdate) -> bool:
        if isinstance(update.payload, OnlyBarUpdate):
            key: tuple[object, ...] = (
                update.source_id,
                update.instrument_id,
                update.payload.bar.bar_type,
                update.ts_event.unix_nanos,
                update.data_version,
            )
        else:
            key = (update.source_id, update.instrument_id, update.data_type, update.source_sequence)
        if key in self._keys:
            return True
        self._keys.add(key)
        return False

    def capture_checkpoint(self) -> object:
        records: list[dict[str, object]] = []
        for key in self._keys:
            if (
                len(key) != 5
                or not isinstance(key[0], OnlyMarketDataSourceId)
                or not isinstance(key[1], OnlyInstrumentId)
                or not isinstance(key[2], OnlyBarType)
                or not isinstance(key[3], int)
                or not isinstance(key[4], OnlyDataVersion)
            ):
                raise ValueError("unsupported MarketData dedup checkpoint key")
            records.append(
                {
                    "bar_type": key[2].to_json(),
                    "data_version": str(key[4]),
                    "instrument_id": key[1].to_json(),
                    "source_id": str(key[0]),
                    "ts_event_ns": key[3],
                }
            )
        return sorted(records, key=lambda item: (str(item["source_id"]), str(item["ts_event_ns"])))

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, list):
            raise ValueError("MarketData dedup checkpoint must be a list")
        self._keys = {
            (
                OnlyMarketDataSourceId(str(item["source_id"])),
                OnlyInstrumentId.from_json(str(item["instrument_id"])),
                OnlyBarType.from_json(str(item["bar_type"])),
                int(item["ts_event_ns"]),
                OnlyDataVersion(str(item["data_version"])),
            )
            for item in payload
            if isinstance(item, dict)
        }


class OnlyMarketDataSequenceTracker:
    def __init__(self) -> None:
        self._last: dict[tuple[object, ...], int] = {}

    def assess(self, update: OnlyMarketDataInboundUpdate) -> tuple[bool, bool]:
        key = (update.source_id, update.instrument_id, update.data_type, update.bar_type)
        current = int(update.source_sequence)
        previous = self._last.get(key)
        if previous is not None and current <= previous:
            return True, False
        gap = previous is not None and current > previous + 1
        self._last[key] = current
        return False, gap

    def capture_checkpoint(self) -> object:
        return [
            {
                "bar_type": None if key[3] is None else cast(OnlyBarType, key[3]).to_json(),
                "data_type": cast(OnlyMarketDataType, key[2]).value,
                "instrument_id": cast(OnlyInstrumentId, key[1]).to_json(),
                "sequence": value,
                "source_id": str(key[0]),
            }
            for key, value in sorted(self._last.items(), key=lambda item: tuple(str(value) for value in item[0]))
        ]

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, list):
            raise ValueError("MarketData sequence checkpoint must be a list")
        self._last = {
            (
                OnlyMarketDataSourceId(str(item["source_id"])),
                OnlyInstrumentId.from_json(str(item["instrument_id"])),
                OnlyMarketDataType(str(item["data_type"])),
                None if item["bar_type"] is None else OnlyBarType.from_json(str(item["bar_type"])),
            ): int(item["sequence"])
            for item in payload
            if isinstance(item, dict)
        }


class OnlyMarketDataGapDetector:
    def __init__(self, calendars: Mapping[OnlyInstrumentId, OnlyTradingCalendar]) -> None:
        self._calendars = calendars
        self._last_bars: dict[OnlyBarType, OnlyBar] = {}

    def assess(self, update: OnlyMarketDataInboundUpdate, sequence_gap: bool) -> tuple[OnlyMarketDataQualityFlag, ...]:
        flags: list[OnlyMarketDataQualityFlag] = []
        if sequence_gap:
            flags.extend((OnlyMarketDataQualityFlag.GAP_DETECTED, OnlyMarketDataQualityFlag.UNEXPECTED_GAP))
        if not isinstance(update.payload, OnlyBarUpdate):
            return tuple(dict.fromkeys(flags))
        bar = update.payload.bar
        previous = self._last_bars.get(bar.bar_type)
        self._last_bars[bar.bar_type] = bar
        if previous is None or bar.bar_start <= previous.bar_end:
            return tuple(dict.fromkeys(flags))
        interval = timedelta(minutes=bar.bar_type.specification.step)
        if bar.bar_start - previous.bar_end < interval:
            return tuple(dict.fromkeys(flags))
        calendar = self._calendars.get(bar.instrument_id)
        same_session = False
        if calendar is not None:
            before = previous.bar_end - timedelta(microseconds=1)
            same_session = calendar.session_at(before) == calendar.session_at(bar.bar_start)
        flags.extend(
            (
                OnlyMarketDataQualityFlag.GAP_DETECTED,
                OnlyMarketDataQualityFlag.UNEXPECTED_GAP
                if same_session
                else OnlyMarketDataQualityFlag.EXPECTED_SESSION_GAP,
            )
        )
        return tuple(dict.fromkeys(flags))

    def capture_checkpoint(self) -> object:
        return [
            [bar_type.to_json(), bar.to_json()]
            for bar_type, bar in sorted(self._last_bars.items(), key=lambda item: item[0].to_json())
        ]

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, list):
            raise ValueError("MarketData gap checkpoint must be a list")
        self._last_bars = {
            OnlyBarType.from_json(str(bar_type)): OnlyBar.from_json(str(bar)) for bar_type, bar in payload
        }


class OnlyMarketDataProcessor:
    def __init__(
        self,
        runtime_id: OnlyRuntimeId,
        clock: OnlyClock,
        instruments: Collection[OnlyInstrumentId],
        source_registry: OnlyMarketDataSourceRegistry,
        pipeline: OnlyMarketDataPipeline,
        dispatcher: OnlyStrategyBarDispatcher,
        deduplicator: OnlyMarketDataDeduplicator,
        sequence_tracker: OnlyMarketDataSequenceTracker,
        gap_detector: OnlyMarketDataGapDetector,
        audit_store: OnlyMarketDataAuditStore,
        event_publisher: OnlyMarketDataEventPublisher,
        before_dispatch: Callable[[OnlyMarketDataUpdateResult], None] | None = None,
        after_dispatch: Callable[[OnlyMarketDataInboundUpdate], None] | None = None,
        after_processing: Callable[[OnlyMarketDataInboundUpdate, OnlyMarketDataProcessingResult], None] | None = None,
    ) -> None:
        self._runtime_id = runtime_id
        self._clock = clock
        self._instruments = instruments
        self._source_registry = source_registry
        self._pipeline = pipeline
        self._dispatcher = dispatcher
        self._deduplicator = deduplicator
        self._sequence_tracker = sequence_tracker
        self._gap_detector = gap_detector
        self._audit_store = audit_store
        self._event_publisher = event_publisher
        self._before_dispatch = before_dispatch or (lambda result: None)
        self._after_dispatch = after_dispatch or (lambda update: None)
        self._after_processing = after_processing or (lambda update, result: None)
        self._sequence = 0

    def capture_checkpoint(self) -> object:
        return {"processing_sequence": self._sequence}

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, dict):
            raise ValueError("MarketData processor checkpoint must be an object")
        self._sequence = int(payload["processing_sequence"])

    def process(self, update: OnlyMarketDataInboundUpdate) -> OnlyMarketDataProcessingResult:
        self._sequence += 1
        validation = self._validate(update)
        if not validation.valid:
            return self._finish(update, OnlyMarketDataProcessingStatus.REJECTED, update.quality, validation)
        if self._deduplicator.seen(update):
            quality = update.quality.with_flags(OnlyMarketDataQualityFlag.DUPLICATE)
            return self._finish(update, OnlyMarketDataProcessingStatus.DUPLICATE, quality, validation)
        stale, sequence_gap = self._sequence_tracker.assess(update)
        if stale:
            quality = update.quality.with_flags(OnlyMarketDataQualityFlag.STALE, OnlyMarketDataQualityFlag.OUT_OF_ORDER)
            return self._finish(update, OnlyMarketDataProcessingStatus.STALE, quality, validation)
        gap_flags = self._gap_detector.assess(update, sequence_gap)
        quality = update.quality.with_flags(*gap_flags) if gap_flags else update.quality
        if not isinstance(update.payload, OnlyBarUpdate):
            return self._finish(update, OnlyMarketDataProcessingStatus.IGNORED, quality, validation)
        try:
            quality_strings = tuple(
                sorted(item.value for item in quality.flags if item is not OnlyMarketDataQualityFlag.VALID)
            )
            pipeline_result = self._pipeline.process_bar(update.payload.bar, input_quality_flags=quality_strings)
            self._before_dispatch(pipeline_result)
            dispatches = self._dispatcher.dispatch(pipeline_result)
            self._after_dispatch(update)
            status = (
                OnlyMarketDataProcessingStatus.GAP_DETECTED
                if OnlyMarketDataQualityFlag.GAP_DETECTED in quality.flags
                else OnlyMarketDataProcessingStatus.APPLIED
            )
            return self._finish(update, status, quality, validation, pipeline_result, dispatches)
        except Exception as exc:
            return self._finish(
                update,
                OnlyMarketDataProcessingStatus.FAILED,
                quality,
                validation,
                failure=OnlyMarketDataFailure(type(exc).__name__, str(exc)),
            )

    def _validate(self, update: OnlyMarketDataInboundUpdate) -> OnlyMarketDataValidationResult:
        reasons: list[str] = []
        if update.runtime_id != self._runtime_id:
            reasons.append("runtime scope mismatch")
        if not self._source_registry.contains(update.source_id):
            reasons.append("source is not registered")
        if update.instrument_id not in self._instruments:
            reasons.append("instrument is not registered")
        if update.ts_event.unix_nanos > self._clock.timestamp_ns():
            reasons.append("lookahead: update is later than Runtime Clock")
        if isinstance(update.payload, OnlyBarUpdate):
            bar = update.payload.bar
            if not bar.is_closed or bar.ts_event != bar.bar_end:
                reasons.append("Processor accepts only correctly closed Bars")
        return OnlyMarketDataValidationResult(not reasons, tuple(reasons))

    def _finish(
        self,
        update: OnlyMarketDataInboundUpdate,
        status: OnlyMarketDataProcessingStatus,
        quality: OnlyMarketDataQuality,
        validation: OnlyMarketDataValidationResult,
        pipeline_result: OnlyMarketDataUpdateResult | None = None,
        dispatches: tuple[OnlyBarDispatchResult, ...] = (),
        failure: OnlyMarketDataFailure | None = None,
    ) -> OnlyMarketDataProcessingResult:
        result = OnlyMarketDataProcessingResult(
            update.update_id,
            update.source_id,
            update.instrument_id,
            update.data_type,
            status,
            self._sequence,
            quality,
            validation,
            pipeline_result,
            dispatches,
            failure,
        )
        processed = OnlyTimestamp.from_unix_nanos(self._clock.timestamp_ns())
        self._audit_store.append(
            OnlyMarketDataAuditRecord(
                f"MD-AUDIT-{self._runtime_id}-{self._sequence:012d}",
                self._runtime_id,
                update.source_id,
                update.update_id,
                update.instrument_id,
                update.data_type,
                status,
                int(update.source_sequence),
                self._sequence,
                update.data_version,
                quality.flags,
                update.ts_event,
                update.ts_init,
                processed,
                validation.reasons,
                None if failure is None else f"{failure.error_type}: {failure.message}",
            )
        )
        self._event_publisher.publish(f"MARKET_DATA_{status.value}", update.update_id, self._sequence)
        self._after_processing(update, result)
        return result

    @property
    def processing_sequence(self) -> int:
        return self._sequence
