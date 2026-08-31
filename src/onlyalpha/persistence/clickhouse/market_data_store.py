"""Typed ClickHouse segment writer and exact-content verifier."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import cast

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.market_data.durable.models import (
    OnlyCanonicalMarketFactRecord,
    OnlyIngestSegment,
    OnlyMarketDataProvenance,
    OnlyMarketDataQualityState,
    OnlyMarketDataRecordBundle,
    OnlyMarketDataRevision,
    OnlyMarketDataScope,
)

from .client import OnlyClickHouseClient
from .version import only_assert_supported_clickhouse_server


class OnlyClickHouseSegmentConflictError(RuntimeError):
    pass


class OnlyClickHouseMarketFactStore:
    def __init__(self, client: OnlyClickHouseClient) -> None:
        only_assert_supported_clickhouse_server(client)
        self._client = client

    def inspect_segment(self, segment: OnlyIngestSegment) -> str:
        counts = self._segment_counts(segment.segment_id)
        raw_count = counts[0]
        fact_count = sum(counts[1:])
        if raw_count == 0 and fact_count == 0:
            return "ABSENT"
        hashes = self._segment_hashes(segment.segment_id)
        if hashes - {segment.content_hash}:
            return "CONFLICT"
        if raw_count == segment.raw_count and fact_count == segment.canonical_count:
            return "EXACT"
        if raw_count <= segment.raw_count and fact_count <= segment.canonical_count:
            return "PARTIAL"
        return "CONFLICT"

    def write_segment(self, segment: OnlyIngestSegment, records: tuple[OnlyMarketDataRecordBundle, ...]) -> None:
        raw_rows = tuple(self._raw_row(segment, ordinal, bundle) for ordinal, bundle in enumerate(records))
        fact_rows: dict[str, list[dict[str, object]]] = {
            "market_trade": [],
            "market_bar": [],
            "market_reference_price": [],
        }
        for bundle in records:
            for fact in bundle.canonical_facts:
                table = _table(fact.data_kind)
                fact_rows[table].append(self._fact_row(segment, fact))
        expected_raw = {str(row["raw_event_id"]): str(row["record_hash"]) for row in raw_rows}
        stored_raw = self._stored_hashes("market_raw_event", "raw_event_id", segment.segment_id)
        _assert_no_conflict(stored_raw, expected_raw, "RAW_SEGMENT_CONFLICT")
        missing_raw = [row for row in raw_rows if str(row["raw_event_id"]) not in stored_raw]
        if missing_raw:
            self._client.insert_json_each_row("market_raw_event", missing_raw)
        for table, rows in fact_rows.items():
            expected = {str(row["canonical_fact_id"]): str(row["record_hash"]) for row in rows}
            stored = self._stored_hashes(table, "canonical_fact_id", segment.segment_id)
            _assert_no_conflict(stored, expected, "CANONICAL_SEGMENT_CONFLICT")
            missing = [row for row in rows if str(row["canonical_fact_id"]) not in stored]
            if missing:
                self._client.insert_json_each_row(table, missing)

    def verify_segment(self, segment: OnlyIngestSegment, records: tuple[OnlyMarketDataRecordBundle, ...]) -> None:
        if self.inspect_segment(segment) != "EXACT":
            raise OnlyClickHouseSegmentConflictError("CLICKHOUSE_SEGMENT_NOT_EXACT")
        raw_rows = tuple(self._raw_row(segment, ordinal, bundle) for ordinal, bundle in enumerate(records))
        expected_raw = {str(row["raw_event_id"]): str(row["record_hash"]) for row in raw_rows}
        if self._stored_hashes("market_raw_event", "raw_event_id", segment.segment_id) != expected_raw:
            raise OnlyClickHouseSegmentConflictError("CLICKHOUSE_RAW_SEGMENT_NOT_EXACT")
        for data_kind, table in (
            ("TRADE", "market_trade"),
            ("BAR", "market_bar"),
            ("MARKET_REFERENCE", "market_reference_price"),
        ):
            expected = {
                fact.canonical_fact_id: str(self._fact_row(segment, fact)["record_hash"])
                for bundle in records
                for fact in bundle.canonical_facts
                if fact.data_kind == data_kind
            }
            if self._stored_hashes(table, "canonical_fact_id", segment.segment_id) != expected:
                raise OnlyClickHouseSegmentConflictError("CLICKHOUSE_CANONICAL_SEGMENT_NOT_EXACT")

    def read_revision_facts(
        self, revision: OnlyMarketDataRevision, scope: OnlyMarketDataScope
    ) -> tuple[OnlyCanonicalMarketFactRecord, ...]:
        segment_ids = tuple(item[0] for item in revision.segment_refs)
        return self._read_facts(segment_ids, scope)

    def read_segment_facts(
        self, segments: tuple[OnlyIngestSegment, ...], scope: OnlyMarketDataScope
    ) -> tuple[OnlyCanonicalMarketFactRecord, ...]:
        if any(self.inspect_segment(item) != "EXACT" for item in segments):
            raise OnlyClickHouseSegmentConflictError("CLICKHOUSE_SEGMENT_NOT_EXACT")
        return self._read_facts(tuple(item.segment_id for item in segments), scope)

    def _read_facts(
        self, segment_ids: tuple[str, ...], scope: OnlyMarketDataScope
    ) -> tuple[OnlyCanonicalMarketFactRecord, ...]:
        if not segment_ids:
            return ()
        quoted = ",".join(_quote(item) for item in segment_ids)
        table = _table(scope.data_kind)
        rows = self._client.query_json(
            "SELECT canonical_fact_id, raw_event_id, source_id, segment_id, capture_session_id, "
            "ts_event_ns, ts_receive_ns, ts_ingest_ns, canonical_payload_json, canonical_payload_hash, "
            "normalizer_id, normalizer_version, quality_state, provenance FROM "
            + table
            + " WHERE segment_id IN ("
            + quoted
            + ") "
            f"AND instrument_id={_quote(scope.instrument_id)} AND ts_event_ns>={scope.start_ns} "
            f"AND ts_event_ns<={scope.end_ns} ORDER BY ts_event_ns, canonical_fact_id, raw_event_id"
        )
        return tuple(self._decode_fact(scope.data_kind, row) for row in rows)

    def _segment_counts(self, segment_id: str) -> tuple[int, int, int, int]:
        result: list[int] = []
        for table in ("market_raw_event", "market_trade", "market_bar", "market_reference_price"):
            rows = self._client.query_json(
                f"SELECT count() AS count FROM {table} WHERE segment_id={_quote(segment_id)}"
            )
            result.append(0 if not rows else int(str(rows[0]["count"])))
        return result[0], result[1], result[2], result[3]

    def _segment_hashes(self, segment_id: str) -> set[str]:
        result: set[str] = set()
        for table in ("market_raw_event", "market_trade", "market_bar", "market_reference_price"):
            rows = self._client.query_json(
                f"SELECT DISTINCT segment_content_hash FROM {table} WHERE segment_id={_quote(segment_id)}"
            )
            result.update(str(row["segment_content_hash"]) for row in rows)
        return result

    def _stored_fact_hashes(self, segment_id: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for table in ("market_trade", "market_bar", "market_reference_price"):
            for key, value in self._stored_hashes(table, "canonical_fact_id", segment_id).items():
                prior = result.setdefault(key, value)
                if prior != value:
                    raise OnlyClickHouseSegmentConflictError("CANONICAL_FACT_STORAGE_CONFLICT")
        return result

    def _stored_hashes(self, table: str, identity: str, segment_id: str) -> dict[str, str]:
        rows = self._client.query_json(
            f"SELECT {identity}, record_hash, count() AS physical_count FROM {table} "
            f"WHERE segment_id={_quote(segment_id)} GROUP BY {identity}, record_hash"
        )
        result: dict[str, str] = {}
        for row in rows:
            key, value = str(row[identity]), str(row["record_hash"])
            prior = result.setdefault(key, value)
            if prior != value:
                raise OnlyClickHouseSegmentConflictError("CLICKHOUSE_IDENTITY_HASH_CONFLICT")
        return result

    @staticmethod
    def _raw_row(segment: OnlyIngestSegment, ordinal: int, bundle: OnlyMarketDataRecordBundle) -> dict[str, object]:
        item = bundle.evidence
        row: dict[str, object] = {
            "raw_event_id": item.raw_event_id,
            "source_id": item.source_id,
            "provider": item.provider,
            "venue": item.venue,
            "market": item.market,
            "stream": item.stream,
            "capture_session_id": item.capture_session_id,
            "segment_id": segment.segment_id,
            "segment_content_hash": segment.content_hash,
            "record_ordinal": ordinal,
            "provider_event_type": item.provider_event_type,
            "provider_event_id": item.provider_event_id,
            "provider_sequence": item.provider_sequence,
            "ts_event_ns": item.ts_event_ns,
            "ts_receive_ns": item.ts_receive_ns,
            "ts_ingest_ns": min((fact.ts_ingest_ns for fact in bundle.canonical_facts), default=item.ts_receive_ns),
            "payload_codec": item.payload_codec,
            "provider_schema": item.provider_schema,
            "provenance": item.provenance.value,
            "raw_payload_base64": base64.b64encode(item.payload).decode("ascii"),
            "raw_sha256": item.raw_sha256,
        }
        row["record_hash"] = only_canonical_fingerprint(row)
        return row

    @staticmethod
    def _fact_row(segment: OnlyIngestSegment, fact: OnlyCanonicalMarketFactRecord) -> dict[str, object]:
        payload = _payload_value(fact.canonical_payload)
        row: dict[str, object] = {
            "canonical_fact_id": fact.canonical_fact_id,
            "source_id": fact.source_id,
            "instrument_id": fact.instrument_id,
            "segment_id": fact.segment_id,
            "segment_content_hash": segment.content_hash,
            "capture_session_id": fact.capture_session_id,
            "raw_event_id": fact.raw_event_id,
            "ts_event_ns": fact.ts_event_ns,
            "ts_receive_ns": fact.ts_receive_ns,
            "ts_ingest_ns": fact.ts_ingest_ns,
            "provenance": fact.provenance.value,
            "quality_state": fact.quality_state.value,
            "canonical_payload_json": only_canonical_json(fact.canonical_payload),
            "canonical_payload_hash": fact.canonical_payload_hash,
            "normalizer_id": fact.normalizer_id,
            "normalizer_version": fact.normalizer_version,
        }
        if fact.data_kind == "TRADE":
            row.update(
                provider_event_id=str(payload["trade_id"]),
                provider_sequence=int(str(payload["sequence"])),
                price=_decimal(payload, "price"),
                price_precision=_precision(payload, "price"),
                quantity=_decimal(payload, "quantity"),
                quantity_precision=_precision(payload, "quantity"),
                aggressor_side=payload.get("aggressor_side"),
            )
        elif fact.data_kind == "BAR":
            row.update(
                bar_start_ns=_iso_ns(payload["bar_start"]),
                bar_end_ns=_iso_ns(payload["bar_end"]),
                bar_type_json=only_canonical_json(payload["bar_type"]),
                open=_decimal(payload, "open"),
                high=_decimal(payload, "high"),
                low=_decimal(payload, "low"),
                close=_decimal(payload, "close"),
                price_precision=_precision(payload, "open"),
                volume=_decimal(payload, "volume"),
                quantity_precision=_precision(payload, "volume"),
                quote_volume=None if payload.get("quote_volume") is None else _decimal(payload, "quote_volume"),
                trade_count=payload.get("trade_count"),
            )
        elif fact.data_kind == "MARKET_REFERENCE":
            price = payload.get("price")
            row.update(
                reference_kind=payload["reference_kind"],
                price=None if price is None else _decimal(payload, "price"),
                price_precision=None if price is None else _precision(payload, "price"),
            )
        row["record_hash"] = only_canonical_fingerprint(row)
        return row

    @staticmethod
    def _decode_fact(data_kind: str, row: Mapping[str, object]) -> OnlyCanonicalMarketFactRecord:
        payload = json.loads(str(row["canonical_payload_json"]))
        if not isinstance(payload, dict):
            raise OnlyClickHouseSegmentConflictError("CANONICAL_PAYLOAD_INVALID")
        return OnlyCanonicalMarketFactRecord(
            str(row["canonical_fact_id"]),
            str(row["raw_event_id"]),
            str(row["source_id"]),
            str(row["segment_id"]),
            str(row["capture_session_id"]),
            data_kind,
            str(payload["instrument_id"]),
            int(str(row["ts_event_ns"])),
            int(str(row["ts_receive_ns"])),
            int(str(row["ts_ingest_ns"])),
            payload,
            str(row["canonical_payload_hash"]),
            str(row["normalizer_id"]),
            str(row["normalizer_version"]),
            OnlyMarketDataQualityState(str(row["quality_state"])),
            OnlyMarketDataProvenance(str(row["provenance"])),
        )


def _table(data_kind: str) -> str:
    try:
        return {"TRADE": "market_trade", "BAR": "market_bar", "MARKET_REFERENCE": "market_reference_price"}[data_kind]
    except KeyError as exc:
        raise ValueError(f"UNSUPPORTED_DURABLE_DATA_KIND:{data_kind}") from exc


def _payload_value(payload: Mapping[str, object]) -> Mapping[str, object]:
    envelope = payload.get("payload")
    if not isinstance(envelope, Mapping) or not isinstance(envelope.get("value"), Mapping):
        raise ValueError("CANONICAL_PAYLOAD_SHAPE_INVALID")
    return cast(Mapping[str, object], envelope["value"])


def _decimal(payload: Mapping[str, object], name: str) -> str:
    value = payload[name]
    if not isinstance(value, Mapping):
        raise ValueError("CANONICAL_DECIMAL_SHAPE_INVALID")
    return str(value["value"])


def _precision(payload: Mapping[str, object], name: str) -> int:
    value = payload[name]
    if not isinstance(value, Mapping):
        raise ValueError("CANONICAL_DECIMAL_SHAPE_INVALID")
    return int(str(value["precision"]))


def _iso_ns(value: object) -> int:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("CANONICAL_TIMESTAMP_MUST_BE_AWARE")
    delta = parsed.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _compatible_subset(stored: Mapping[str, str], expected: Mapping[str, str]) -> bool:
    return all(expected.get(key) == value for key, value in stored.items())


def _assert_no_conflict(stored: Mapping[str, str], expected: Mapping[str, str], message: str) -> None:
    if not _compatible_subset(stored, expected):
        raise OnlyClickHouseSegmentConflictError(message)


__all__ = [name for name in globals() if name.startswith("Only")]
