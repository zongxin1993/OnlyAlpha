"""Immutable DTOs for historical and real-time market-data ingress."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime

from onlyalpha.core.clock import OnlyTimeAdvanceResult
from onlyalpha.data.enums import (
    OnlyHistoricalMergePolicy,
    OnlyHistoricalReplayState,
    OnlyMarketDataConnectionState,
    OnlyMarketDataProcessingStatus,
    OnlyMarketDataQualityFlag,
    OnlyMarketDataRequestStatus,
    OnlyMarketDataType,
    OnlyPriceAdjustmentMode,
)
from onlyalpha.data.identifiers import (
    OnlyDataSequence,
    OnlyDataVersion,
    OnlyMarketDataGatewayId,
    OnlyMarketDataSourceId,
    OnlyMarketDataUpdateId,
)
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.domain.market import OnlyBar, OnlyBarType, OnlyQuoteTick, OnlyTradeTick
from onlyalpha.domain.time import OnlyTimestamp, only_require_utc


@dataclass(frozen=True, slots=True)
class OnlyMarketDataQuality:
    flags: frozenset[OnlyMarketDataQualityFlag] = frozenset({OnlyMarketDataQualityFlag.VALID})

    def with_flags(self, *flags: OnlyMarketDataQualityFlag) -> OnlyMarketDataQuality:
        retained = set(self.flags)
        retained.discard(OnlyMarketDataQualityFlag.VALID)
        retained.update(flags)
        return OnlyMarketDataQuality(frozenset(retained or {OnlyMarketDataQualityFlag.VALID}))


@dataclass(frozen=True, slots=True)
class OnlyBarUpdate:
    bar: OnlyBar


@dataclass(frozen=True, slots=True)
class OnlyQuoteTickUpdate:
    quote: OnlyQuoteTick


@dataclass(frozen=True, slots=True)
class OnlyTradeTickUpdate:
    trade: OnlyTradeTick


@dataclass(frozen=True, slots=True)
class OnlyInstrumentStatusUpdate:
    instrument_id: OnlyInstrumentId
    status: str

    def __post_init__(self) -> None:
        if not self.status.strip():
            raise ValueError("instrument status cannot be blank")


OnlyMarketDataPayload = OnlyBarUpdate | OnlyQuoteTickUpdate | OnlyTradeTickUpdate | OnlyInstrumentStatusUpdate


@dataclass(frozen=True, slots=True)
class OnlyMarketDataInboundUpdate:
    update_id: OnlyMarketDataUpdateId
    runtime_id: OnlyRuntimeId
    source_id: OnlyMarketDataSourceId
    source_sequence: OnlyDataSequence
    data_version: OnlyDataVersion
    instrument_id: OnlyInstrumentId
    data_type: OnlyMarketDataType
    payload: OnlyMarketDataPayload
    ts_event: OnlyTimestamp
    ts_init: OnlyTimestamp
    quality: OnlyMarketDataQuality = OnlyMarketDataQuality()
    correlation_id: str | None = None
    metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if self.ts_init.unix_nanos < self.ts_event.unix_nanos:
            raise ValueError("market-data ts_init cannot precede ts_event")
        payload_instrument = (
            self.payload.bar.instrument_id
            if isinstance(self.payload, OnlyBarUpdate)
            else self.payload.quote.instrument_id
            if isinstance(self.payload, OnlyQuoteTickUpdate)
            else self.payload.trade.instrument_id
            if isinstance(self.payload, OnlyTradeTickUpdate)
            else self.payload.instrument_id
        )
        if payload_instrument != self.instrument_id:
            raise ValueError("market-data envelope instrument does not match payload")
        expected = {
            OnlyBarUpdate: OnlyMarketDataType.BAR,
            OnlyQuoteTickUpdate: OnlyMarketDataType.QUOTE,
            OnlyTradeTickUpdate: OnlyMarketDataType.TRADE,
            OnlyInstrumentStatusUpdate: OnlyMarketDataType.INSTRUMENT_STATUS,
        }[type(self.payload)]
        if self.data_type is not expected:
            raise ValueError("market-data envelope type does not match payload")

    @property
    def bar_type(self) -> OnlyBarType | None:
        return self.payload.bar.bar_type if isinstance(self.payload, OnlyBarUpdate) else None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object]
        if isinstance(self.payload, OnlyBarUpdate):
            payload = {"kind": "BAR", "value": self.payload.bar.to_dict()}
        elif isinstance(self.payload, OnlyQuoteTickUpdate):
            payload = {"kind": "QUOTE", "value": self.payload.quote.to_dict()}
        elif isinstance(self.payload, OnlyTradeTickUpdate):
            payload = {"kind": "TRADE", "value": self.payload.trade.to_dict()}
        else:
            payload = {"kind": "INSTRUMENT_STATUS", "status": self.payload.status}
        return {
            "schema_version": 1,
            "update_id": str(self.update_id),
            "runtime_id": str(self.runtime_id),
            "source_id": str(self.source_id),
            "source_sequence": int(self.source_sequence),
            "data_version": str(self.data_version),
            "instrument_id": str(self.instrument_id),
            "data_type": self.data_type.value,
            "payload": payload,
            "ts_event": self.ts_event.unix_nanos,
            "ts_init": self.ts_init.unix_nanos,
            "quality_flags": sorted(item.value for item in self.quality.flags),
            "correlation_id": self.correlation_id,
            "metadata": [list(item) for item in self.metadata],
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> OnlyMarketDataInboundUpdate:
        payload_raw = raw["payload"]
        if not isinstance(payload_raw, Mapping):
            raise ValueError("market-data payload must be a mapping")
        kind = str(payload_raw["kind"])
        instrument_id = OnlyInstrumentId.parse(str(raw["instrument_id"]))
        value = payload_raw.get("value")
        if kind == "BAR" and isinstance(value, Mapping):
            payload: OnlyMarketDataPayload = OnlyBarUpdate(OnlyBar.from_dict(value))
        elif kind == "QUOTE" and isinstance(value, Mapping):
            payload = OnlyQuoteTickUpdate(OnlyQuoteTick.from_dict(value))
        elif kind == "TRADE" and isinstance(value, Mapping):
            payload = OnlyTradeTickUpdate(OnlyTradeTick.from_dict(value))
        elif kind == "INSTRUMENT_STATUS":
            payload = OnlyInstrumentStatusUpdate(instrument_id, str(payload_raw["status"]))
        else:
            raise ValueError("unsupported market-data payload kind")
        quality_raw = raw["quality_flags"]
        metadata_raw = raw["metadata"]
        if not isinstance(quality_raw, list) or not isinstance(metadata_raw, list):
            raise ValueError("quality_flags and metadata must be lists")
        metadata: list[tuple[str, str]] = []
        for item in metadata_raw:
            if not isinstance(item, list) or len(item) != 2:
                raise ValueError("metadata entries must be pairs")
            metadata.append((str(item[0]), str(item[1])))
        return cls(
            OnlyMarketDataUpdateId(str(raw["update_id"])),
            OnlyRuntimeId(str(raw["runtime_id"])),
            OnlyMarketDataSourceId(str(raw["source_id"])),
            OnlyDataSequence(int(str(raw["source_sequence"]))),
            OnlyDataVersion(str(raw["data_version"])),
            instrument_id,
            OnlyMarketDataType(str(raw["data_type"])),
            payload,
            OnlyTimestamp.from_unix_nanos(int(str(raw["ts_event"]))),
            OnlyTimestamp.from_unix_nanos(int(str(raw["ts_init"]))),
            OnlyMarketDataQuality(frozenset(OnlyMarketDataQualityFlag(str(item)) for item in quality_raw)),
            None if raw.get("correlation_id") is None else str(raw["correlation_id"]),
            tuple(metadata),
        )


@dataclass(frozen=True, slots=True)
class OnlyHistoricalDataRange:
    start_time: datetime
    end_time: datetime

    def __post_init__(self) -> None:
        only_require_utc(self.start_time, "historical start_time")
        only_require_utc(self.end_time, "historical end_time")
        if self.start_time >= self.end_time:
            raise ValueError("historical range must be increasing and is [start, end)")


@dataclass(frozen=True, slots=True)
class OnlyHistoricalBarRequest:
    request_id: str
    instrument_ids: frozenset[OnlyInstrumentId]
    bar_types: frozenset[OnlyBarType]
    data_range: OnlyHistoricalDataRange
    data_version: OnlyDataVersion
    adjustment_mode: OnlyPriceAdjustmentMode = OnlyPriceAdjustmentMode.RAW
    batch_size: int = 1024
    metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.request_id.strip() or not self.instrument_ids or not self.bar_types or self.batch_size <= 0:
            raise ValueError("historical Bar request requires id, instruments, bar types and positive batch size")
        if self.adjustment_mode is not OnlyPriceAdjustmentMode.RAW:
            raise ValueError("only RAW historical Bars are supported")


@dataclass(frozen=True, slots=True)
class OnlyHistoricalQuoteRequest:
    request_id: str
    instrument_ids: frozenset[OnlyInstrumentId]
    data_range: OnlyHistoricalDataRange
    data_version: OnlyDataVersion
    batch_size: int = 1024


@dataclass(frozen=True, slots=True)
class OnlyHistoricalTradeRequest:
    request_id: str
    instrument_ids: frozenset[OnlyInstrumentId]
    data_range: OnlyHistoricalDataRange
    data_version: OnlyDataVersion
    batch_size: int = 1024


@dataclass(frozen=True, slots=True)
class OnlyHistoricalDataStream[T]:
    records: tuple[T, ...]
    batch_size: int

    def __iter__(self) -> Iterator[T]:
        return iter(self.records)

    def batches(self) -> Iterator[tuple[T, ...]]:
        for offset in range(0, len(self.records), self.batch_size):
            yield self.records[offset : offset + self.batch_size]


@dataclass(frozen=True, slots=True)
class OnlyMarketDataValidationResult:
    valid: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OnlyMarketDataFailure:
    error_type: str
    message: str


@dataclass(frozen=True, slots=True)
class OnlyMarketDataProcessingResult:
    update_id: OnlyMarketDataUpdateId
    source_id: OnlyMarketDataSourceId
    instrument_id: OnlyInstrumentId
    data_type: OnlyMarketDataType
    status: OnlyMarketDataProcessingStatus
    processing_sequence: int
    quality: OnlyMarketDataQuality
    validation: OnlyMarketDataValidationResult
    pipeline_result: object | None = None
    dispatches: tuple[object, ...] = ()
    failure: OnlyMarketDataFailure | None = None


@dataclass(frozen=True, slots=True)
class OnlyMarketDataConnectionSnapshot:
    gateway_id: OnlyMarketDataGatewayId
    state: OnlyMarketDataConnectionState


@dataclass(frozen=True, slots=True)
class OnlyMarketDataConnectionResult:
    status: OnlyMarketDataRequestStatus
    snapshot: OnlyMarketDataConnectionSnapshot
    reason: str | None = None


OnlyMarketDataAuthenticationResult = OnlyMarketDataConnectionResult
OnlyMarketDataDisconnectResult = OnlyMarketDataConnectionResult


@dataclass(frozen=True, slots=True)
class OnlyMarketDataSubscriptionRequest:
    request_id: str
    source_id: OnlyMarketDataSourceId
    instrument_ids: frozenset[OnlyInstrumentId]
    data_types: frozenset[OnlyMarketDataType]
    bar_types: frozenset[OnlyBarType] = frozenset()


@dataclass(frozen=True, slots=True)
class OnlyMarketDataUnsubscriptionRequest:
    request_id: str
    subscription_id: str


@dataclass(frozen=True, slots=True)
class OnlyMarketDataSubscriptionResult:
    status: OnlyMarketDataRequestStatus
    subscription_id: str | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class OnlyHistoricalReplayConfig:
    streams: tuple[OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate], ...]
    merge_policy: OnlyHistoricalMergePolicy = OnlyHistoricalMergePolicy.STABLE_TOTAL_ORDER
    source_priority: tuple[OnlyMarketDataSourceId, ...] = ()


@dataclass(slots=True)
class OnlyHistoricalReplayCursor:
    updates: tuple[OnlyMarketDataInboundUpdate, ...]
    index: int = 0
    state: OnlyHistoricalReplayState = OnlyHistoricalReplayState.PREPARED
    results: list[OnlyMarketDataProcessingResult] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class OnlyHistoricalReplayEvent:
    index: int
    update: OnlyMarketDataInboundUpdate
    result: OnlyMarketDataProcessingResult
    clock_time_ns: int
    advance: OnlyTimeAdvanceResult


@dataclass(frozen=True, slots=True)
class OnlyHistoricalReplayResult:
    state: OnlyHistoricalReplayState
    processed: int
    applied: int
    duplicate: int
    gap_detected: int
    rejected: int
    failed: int
    events: tuple[OnlyHistoricalReplayEvent, ...]


@dataclass(frozen=True, slots=True)
class OnlyHistoricalDataQueryResult:
    source_id: OnlyMarketDataSourceId
    data_version: OnlyDataVersion
    record_count: int
    quality: OnlyMarketDataQuality


@dataclass(frozen=True, slots=True, order=True)
class OnlyMarketDataSourcePriority:
    value: int

    def __post_init__(self) -> None:
        if self.value < 0:
            raise ValueError("market-data source priority cannot be negative")
