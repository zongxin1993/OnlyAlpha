"""Deterministic local historical and reference data sources."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path

from onlyalpha.data.enums import OnlyMarketDataCapability, OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.data.models import (
    OnlyHistoricalBarRequest,
    OnlyHistoricalDataStream,
    OnlyHistoricalQuoteRequest,
    OnlyHistoricalTradeRequest,
    OnlyMarketDataInboundUpdate,
)
from onlyalpha.data.ports import OnlyMarketDataCapabilities
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.identifiers import OnlyCalendarId, OnlyInstrumentId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.market_rules import OnlyMarketRule
from onlyalpha.domain.time import OnlyTimestamp


class OnlyHistoricalDataSourceError(RuntimeError):
    pass


_HISTORICAL_CAPABILITIES: OnlyMarketDataCapabilities = frozenset(
    {
        OnlyMarketDataCapability.QUERY_HISTORICAL_BAR,
        OnlyMarketDataCapability.QUERY_HISTORICAL_QUOTE,
        OnlyMarketDataCapability.QUERY_HISTORICAL_TRADE,
    }
)


class OnlyInMemoryHistoricalDataSource:
    def __init__(self, source_id: OnlyMarketDataSourceId, updates: Iterable[OnlyMarketDataInboundUpdate] = ()) -> None:
        self._source_id = source_id
        records = tuple(updates)
        if any(item.source_id != source_id for item in records):
            raise ValueError("all in-memory updates must belong to the source")
        self._updates = records

    @property
    def source_id(self) -> OnlyMarketDataSourceId:
        return self._source_id

    @property
    def capabilities(self) -> OnlyMarketDataCapabilities:
        return _HISTORICAL_CAPABILITIES

    def load_bars(self, request: OnlyHistoricalBarRequest) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        return OnlyHistoricalDataStream(
            tuple(
                item
                for item in self._updates
                if self._matches(
                    item, request.instrument_ids, request.data_range.start_time, request.data_range.end_time
                )
                and item.data_type is OnlyMarketDataType.BAR
                and item.bar_type in request.bar_types
                and item.data_version == request.data_version
            ),
            request.batch_size,
        )

    def load_quotes(self, request: OnlyHistoricalQuoteRequest) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        return OnlyHistoricalDataStream(
            tuple(
                item
                for item in self._updates
                if self._matches(
                    item, request.instrument_ids, request.data_range.start_time, request.data_range.end_time
                )
                and item.data_type is OnlyMarketDataType.QUOTE
                and item.data_version == request.data_version
            ),
            request.batch_size,
        )

    def load_trades(self, request: OnlyHistoricalTradeRequest) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        return OnlyHistoricalDataStream(
            tuple(
                item
                for item in self._updates
                if self._matches(
                    item, request.instrument_ids, request.data_range.start_time, request.data_range.end_time
                )
                and item.data_type is OnlyMarketDataType.TRADE
                and item.data_version == request.data_version
            ),
            request.batch_size,
        )

    @staticmethod
    def _matches(
        update: OnlyMarketDataInboundUpdate,
        instrument_ids: frozenset[OnlyInstrumentId],
        start: datetime,
        end: datetime,
    ) -> bool:
        event = update.ts_event.to_datetime()
        return update.instrument_id in instrument_ids and start <= event < end


class _OnlySerializedHistoricalDataSource(OnlyInMemoryHistoricalDataSource):
    def __init__(self, source_id: OnlyMarketDataSourceId, updates: Iterable[OnlyMarketDataInboundUpdate]) -> None:
        super().__init__(source_id, updates)


class OnlyCsvHistoricalDataSource(_OnlySerializedHistoricalDataSource):
    """Strict small-file import format with one lossless JSON envelope per row."""

    REQUIRED_COLUMNS = ("update_json",)

    def __init__(self, source_id: OnlyMarketDataSourceId, path: str | Path) -> None:
        source_path = Path(path)
        try:
            with source_path.open(encoding="utf-8", newline="") as stream:
                reader = csv.DictReader(stream)
                if tuple(reader.fieldnames or ()) != self.REQUIRED_COLUMNS:
                    raise OnlyHistoricalDataSourceError("CSV schema must be exactly: update_json")
                updates = tuple(self._decode(row["update_json"], source_id) for row in reader)
        except (OSError, csv.Error, json.JSONDecodeError, KeyError, ValueError) as exc:
            if isinstance(exc, OnlyHistoricalDataSourceError):
                raise
            raise OnlyHistoricalDataSourceError(f"invalid historical CSV: {exc}") from exc
        super().__init__(source_id, updates)

    @staticmethod
    def write(path: str | Path, updates: Iterable[OnlyMarketDataInboundUpdate]) -> None:
        with Path(path).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=OnlyCsvHistoricalDataSource.REQUIRED_COLUMNS)
            writer.writeheader()
            for update in updates:
                writer.writerow({"update_json": json.dumps(update.to_dict(), sort_keys=True, separators=(",", ":"))})

    @staticmethod
    def _decode(raw: str, source_id: OnlyMarketDataSourceId) -> OnlyMarketDataInboundUpdate:
        payload = json.loads(raw)
        if not isinstance(payload, Mapping):
            raise ValueError("CSV update_json must decode to an object")
        update = OnlyMarketDataInboundUpdate.from_dict(payload)
        if update.source_id != source_id:
            raise ValueError("CSV source id mismatch")
        return update


class OnlyParquetHistoricalDataSource:
    """Version-preserving local Parquet reader using pyarrow filters and batches."""

    REQUIRED_COLUMNS = (
        "source_id",
        "instrument_id",
        "data_type",
        "bar_type",
        "ts_event",
        "data_version",
        "update_json",
    )

    def __init__(self, source_id: OnlyMarketDataSourceId, path: str | Path) -> None:
        try:
            import pyarrow.dataset as dataset  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - dependency is declared by the package
            raise OnlyHistoricalDataSourceError("pyarrow is required for Parquet historical data") from exc
        source_path = Path(path)
        try:
            parquet = dataset.dataset(source_path, format="parquet", partitioning="hive")
            names = tuple(parquet.schema.names)
            if any(column not in names for column in self.REQUIRED_COLUMNS):
                raise OnlyHistoricalDataSourceError(f"Parquet schema requires {self.REQUIRED_COLUMNS}")
        except OnlyHistoricalDataSourceError:
            raise
        except Exception as exc:
            raise OnlyHistoricalDataSourceError(f"invalid historical Parquet: {exc}") from exc
        self._source_id = source_id
        self._dataset = parquet

    @property
    def source_id(self) -> OnlyMarketDataSourceId:
        return self._source_id

    @property
    def capabilities(self) -> OnlyMarketDataCapabilities:
        return _HISTORICAL_CAPABILITIES

    def load_bars(self, request: OnlyHistoricalBarRequest) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        bar_type_ids = frozenset(
            json.dumps(item.to_dict(), sort_keys=True, separators=(",", ":")) for item in request.bar_types
        )
        return self._load(
            OnlyMarketDataType.BAR,
            request.instrument_ids,
            OnlyTimestamp.from_datetime(request.data_range.start_time).unix_nanos,
            OnlyTimestamp.from_datetime(request.data_range.end_time).unix_nanos,
            request.data_version,
            request.batch_size,
            bar_type_ids,
        )

    def load_quotes(self, request: OnlyHistoricalQuoteRequest) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        return self._load(
            OnlyMarketDataType.QUOTE,
            request.instrument_ids,
            OnlyTimestamp.from_datetime(request.data_range.start_time).unix_nanos,
            OnlyTimestamp.from_datetime(request.data_range.end_time).unix_nanos,
            request.data_version,
            request.batch_size,
        )

    def load_trades(self, request: OnlyHistoricalTradeRequest) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        return self._load(
            OnlyMarketDataType.TRADE,
            request.instrument_ids,
            OnlyTimestamp.from_datetime(request.data_range.start_time).unix_nanos,
            OnlyTimestamp.from_datetime(request.data_range.end_time).unix_nanos,
            request.data_version,
            request.batch_size,
        )

    def _load(
        self,
        data_type: OnlyMarketDataType,
        instrument_ids: frozenset[OnlyInstrumentId],
        start_ns: int,
        end_ns: int,
        data_version: OnlyDataVersion,
        batch_size: int,
        bar_type_ids: frozenset[str] | None = None,
    ) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        import pyarrow.dataset as dataset

        condition = (
            (dataset.field("source_id") == str(self._source_id))
            & dataset.field("instrument_id").isin([str(item) for item in sorted(instrument_ids, key=str)])
            & (dataset.field("data_type") == data_type.value)
            & (dataset.field("ts_event") >= start_ns)
            & (dataset.field("ts_event") < end_ns)
            & (dataset.field("data_version") == str(data_version))
        )
        if bar_type_ids is not None:
            condition &= dataset.field("bar_type").isin(sorted(bar_type_ids))
        updates: list[OnlyMarketDataInboundUpdate] = []
        try:
            for batch in self._dataset.to_batches(
                columns=["update_json"],
                filter=condition,
                batch_size=batch_size,
            ):
                for row in batch.to_pylist():
                    updates.append(OnlyMarketDataInboundUpdate.from_dict(json.loads(str(row["update_json"]))))
        except Exception as exc:
            raise OnlyHistoricalDataSourceError(f"Parquet query failed: {exc}") from exc
        return OnlyHistoricalDataStream(tuple(updates), batch_size)

    @staticmethod
    def write(path: str | Path, updates: Iterable[OnlyMarketDataInboundUpdate]) -> None:
        try:
            import pyarrow as pa
            import pyarrow.parquet as parquet  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover
            raise OnlyHistoricalDataSourceError("pyarrow is required for Parquet historical data") from exc
        records = tuple(updates)
        table = pa.table(
            {
                "source_id": [str(item.source_id) for item in records],
                "instrument_id": [str(item.instrument_id) for item in records],
                "data_type": [item.data_type.value for item in records],
                "bar_type": [
                    ""
                    if item.bar_type is None
                    else json.dumps(item.bar_type.to_dict(), sort_keys=True, separators=(",", ":"))
                    for item in records
                ],
                "ts_event": [item.ts_event.unix_nanos for item in records],
                "data_version": [str(item.data_version) for item in records],
                "update_json": [json.dumps(item.to_dict(), sort_keys=True, separators=(",", ":")) for item in records],
            }
        )
        parquet.write_table(table, Path(path))


class OnlyInMemoryReferenceDataSource:
    def __init__(
        self,
        source_id: OnlyMarketDataSourceId,
        instruments: Mapping[OnlyInstrumentId, OnlyInstrument],
        calendars: Mapping[OnlyCalendarId, OnlyTradingCalendar],
        market_rules: Mapping[OnlyInstrumentId, OnlyMarketRule],
    ) -> None:
        self._source_id = source_id
        self._instruments = instruments
        self._calendars = calendars
        self._market_rules = market_rules

    @property
    def source_id(self) -> OnlyMarketDataSourceId:
        return self._source_id

    def instrument(self, instrument_id: OnlyInstrumentId) -> OnlyInstrument | None:
        return self._instruments.get(instrument_id)

    def calendar(self, calendar_id: OnlyCalendarId) -> OnlyTradingCalendar | None:
        return self._calendars.get(calendar_id)

    def market_rule(self, instrument_id: OnlyInstrumentId) -> OnlyMarketRule | None:
        return self._market_rules.get(instrument_id)


OnlyFileReferenceDataSource = OnlyInMemoryReferenceDataSource
