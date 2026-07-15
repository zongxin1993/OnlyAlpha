"""Immutable market-data processing audit."""

from dataclasses import dataclass

from onlyalpha.data.enums import OnlyMarketDataProcessingStatus, OnlyMarketDataQualityFlag, OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId, OnlyMarketDataUpdateId
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp


@dataclass(frozen=True, slots=True)
class OnlyMarketDataAuditRecord:
    audit_id: str
    runtime_id: OnlyRuntimeId
    source_id: OnlyMarketDataSourceId
    update_id: OnlyMarketDataUpdateId
    instrument_id: OnlyInstrumentId
    data_type: OnlyMarketDataType
    status: OnlyMarketDataProcessingStatus
    source_sequence: int
    processing_sequence: int
    data_version: OnlyDataVersion
    quality_flags: frozenset[OnlyMarketDataQualityFlag]
    ts_event: OnlyTimestamp
    ts_init: OnlyTimestamp
    ts_processed: OnlyTimestamp
    validation_reasons: tuple[str, ...]
    failure: str | None


class OnlyMarketDataAuditStore:
    def __init__(self) -> None:
        self._records: list[OnlyMarketDataAuditRecord] = []

    def append(self, record: OnlyMarketDataAuditRecord) -> None:
        self._records.append(record)

    def records(self) -> tuple[OnlyMarketDataAuditRecord, ...]:
        return tuple(self._records)


class OnlyMarketDataEventPublisher:
    """Small past-fact sink kept separate from Processor state changes."""

    def __init__(self) -> None:
        self._facts: list[tuple[str, str, int]] = []

    def publish(self, event_type: str, update_id: OnlyMarketDataUpdateId, sequence: int) -> None:
        self._facts.append((event_type, str(update_id), sequence))

    @property
    def facts(self) -> tuple[tuple[str, str, int], ...]:
        return tuple(self._facts)
