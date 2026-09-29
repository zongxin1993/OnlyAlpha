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
    OnlyVerifiedSegmentBatch,
)

from .client import OnlyClickHouseClient
from .version import only_assert_supported_clickhouse_server

_SEGMENT_VERIFY_CHUNK_SIZE = 1_000
_ROW_INSERT_CHUNK_SIZE = 10_000
_SEGMENT_TABLES = ("market_raw_event", "market_trade", "market_bar", "market_reference_price")
_TABLE_IDENTITIES = {
    "market_raw_event": ("raw_event_id",),
    "market_trade": ("canonical_fact_id", "raw_event_id"),
    "market_bar": ("canonical_fact_id", "raw_event_id"),
    "market_reference_price": ("canonical_fact_id", "raw_event_id"),
}


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
        self.write_segments((segment,), {segment.segment_id: records})

    def write_segments(
        self,
        segments: tuple[OnlyIngestSegment, ...],
        records_by_segment: Mapping[str, tuple[OnlyMarketDataRecordBundle, ...]],
    ) -> None:
        OnlyVerifiedSegmentBatch.build(segments, records_by_segment, None)
        rows_by_table = self._expected_rows(segments, records_by_segment)
        states = self._classify_segments(segments, rows_by_table)
        if any(state in {"PARTIAL", "CONFLICT"} for state in states.values()):
            failed = next(state for state in states.values() if state in {"PARTIAL", "CONFLICT"})
            raise OnlyClickHouseSegmentConflictError(f"CLICKHOUSE_SEGMENT_{failed}")
        absent = {segment_id for segment_id, state in states.items() if state == "ABSENT"}
        for table, rows in rows_by_table.items():
            missing = [row for row in rows if str(row["segment_id"]) in absent]
            for offset in range(0, len(missing), _ROW_INSERT_CHUNK_SIZE):
                self._client.insert_json_each_row(table, missing[offset : offset + _ROW_INSERT_CHUNK_SIZE])

    def verify_segment(self, segment: OnlyIngestSegment, records: tuple[OnlyMarketDataRecordBundle, ...]) -> None:
        self.verify_segments(
            (segment,),
            {segment.segment_id: records},
            segment.recovery_scope() if segment.canonical_count else None,
        )

    def verify_segments(
        self,
        segments: tuple[OnlyIngestSegment, ...],
        records_by_segment: Mapping[str, tuple[OnlyMarketDataRecordBundle, ...]],
        scope: OnlyMarketDataScope | None = None,
    ) -> OnlyVerifiedSegmentBatch:
        verified = OnlyVerifiedSegmentBatch.build(segments, records_by_segment, scope)
        states = self._classify_segments(segments, self._expected_rows(segments, records_by_segment))
        if any(state != "EXACT" for state in states.values()):
            raise OnlyClickHouseSegmentConflictError("CLICKHOUSE_SEGMENT_NOT_EXACT")
        return verified

    def _expected_rows(
        self,
        segments: tuple[OnlyIngestSegment, ...],
        records_by_segment: Mapping[str, tuple[OnlyMarketDataRecordBundle, ...]],
    ) -> dict[str, list[dict[str, object]]]:
        rows_by_table: dict[str, list[dict[str, object]]] = {table: [] for table in _SEGMENT_TABLES}
        for segment in segments:
            records = records_by_segment[segment.segment_id]
            rows_by_table["market_raw_event"].extend(
                self._raw_row(segment, ordinal, bundle) for ordinal, bundle in enumerate(records)
            )
            for bundle in records:
                for fact in bundle.canonical_facts:
                    rows_by_table[_table(fact.data_kind)].append(self._fact_row(segment, fact))
        return rows_by_table

    def _classify_segments(
        self,
        segments: tuple[OnlyIngestSegment, ...],
        rows_by_table: Mapping[str, list[dict[str, object]]],
    ) -> dict[str, str]:
        segment_ids = tuple(item.segment_id for item in segments)
        expected: dict[str, dict[str, dict[tuple[str, ...], tuple[str, str]]]] = {
            table: {segment_id: {} for segment_id in segment_ids} for table in _SEGMENT_TABLES
        }
        for table, rows in rows_by_table.items():
            identities = _TABLE_IDENTITIES[table]
            for row in rows:
                segment_id = str(row["segment_id"])
                identity = tuple(str(row[item]) for item in identities)
                if identity in expected[table][segment_id]:
                    raise ValueError("MARKET_DATA_EXPECTED_ROW_IDENTITY_DUPLICATE")
                expected[table][segment_id][identity] = (
                    str(row["record_hash"]),
                    str(row["segment_content_hash"]),
                )
        stored = self._stored_rows(segment_ids)
        states: dict[str, str] = {}
        for segment in segments:
            if not any(stored[table][segment.segment_id] for table in _SEGMENT_TABLES):
                states[segment.segment_id] = "ABSENT"
                continue
            conflict = False
            partial = False
            for table in _SEGMENT_TABLES:
                wanted = expected[table][segment.segment_id]
                actual = stored[table][segment.segment_id]
                for identity, (record_hash, content_hash, physical_count) in actual.items():
                    if (
                        identity not in wanted
                        or wanted[identity] != (record_hash, content_hash)
                        or content_hash != segment.content_hash
                        or physical_count != 1
                    ):
                        conflict = True
                partial = partial or set(actual) != set(wanted)
            states[segment.segment_id] = "CONFLICT" if conflict else "PARTIAL" if partial else "EXACT"
        return states

    def _stored_rows(
        self, segment_ids: tuple[str, ...]
    ) -> dict[str, dict[str, dict[tuple[str, ...], tuple[str, str, int]]]]:
        result: dict[str, dict[str, dict[tuple[str, ...], tuple[str, str, int]]]] = {
            table: {segment_id: {} for segment_id in segment_ids} for table in _SEGMENT_TABLES
        }
        for offset in range(0, len(segment_ids), _SEGMENT_VERIFY_CHUNK_SIZE):
            chunk = segment_ids[offset : offset + _SEGMENT_VERIFY_CHUNK_SIZE]
            quoted = ",".join(_quote(item) for item in chunk)
            for table, identities in _TABLE_IDENTITIES.items():
                identity_sql = ", ".join(identities)
                rows = self._client.query_json(
                    f"SELECT segment_id, {identity_sql}, record_hash, segment_content_hash, "
                    f"count() AS physical_count FROM {table} WHERE segment_id IN ({quoted}) "
                    f"GROUP BY segment_id, {identity_sql}, record_hash, segment_content_hash"
                )
                for row in rows:
                    segment_id = str(row["segment_id"])
                    if segment_id not in result[table]:
                        raise OnlyClickHouseSegmentConflictError("CLICKHOUSE_UNEXPECTED_SEGMENT_ID")
                    identity = tuple(str(row[item]) for item in identities)
                    if identity in result[table][segment_id]:
                        raise OnlyClickHouseSegmentConflictError("CLICKHOUSE_IDENTITY_HASH_CONFLICT")
                    result[table][segment_id][identity] = (
                        str(row["record_hash"]),
                        str(row["segment_content_hash"]),
                        int(str(row["physical_count"])),
                    )
        return result

    def read_revision_facts(
        self, revision: OnlyMarketDataRevision, scope: OnlyMarketDataScope
    ) -> tuple[OnlyCanonicalMarketFactRecord, ...]:
        segment_ids = tuple(item[0] for item in revision.segment_refs)
        return self._read_facts(segment_ids, scope)

    def read_segment_facts(
        self, segments: tuple[OnlyIngestSegment, ...], scope: OnlyMarketDataScope
    ) -> tuple[OnlyCanonicalMarketFactRecord, ...]:
        self._verify_segments_exact(segments)
        return self._read_facts(tuple(item.segment_id for item in segments), scope)

    def _verify_segments_exact(self, segments: tuple[OnlyIngestSegment, ...]) -> None:
        expected = {item.segment_id: item for item in segments}
        if len(expected) != len(segments):
            raise OnlyClickHouseSegmentConflictError("CLICKHOUSE_SEGMENT_NOT_EXACT")
        raw_counts = {segment_id: 0 for segment_id in expected}
        canonical_counts = {segment_id: 0 for segment_id in expected}
        hashes = {segment_id: set[str]() for segment_id in expected}
        segment_ids = tuple(expected)
        for offset in range(0, len(segment_ids), _SEGMENT_VERIFY_CHUNK_SIZE):
            chunk = segment_ids[offset : offset + _SEGMENT_VERIFY_CHUNK_SIZE]
            quoted = ",".join(_quote(item) for item in chunk)
            for table in _SEGMENT_TABLES:
                rows = self._client.query_json(
                    "SELECT segment_id, segment_content_hash, count() AS physical_count FROM "
                    f"{table} WHERE segment_id IN ({quoted}) "
                    "GROUP BY segment_id, segment_content_hash"
                )
                for row in rows:
                    segment_id = str(row["segment_id"])
                    if segment_id not in expected:
                        raise OnlyClickHouseSegmentConflictError("CLICKHOUSE_SEGMENT_NOT_EXACT")
                    count = int(str(row["physical_count"]))
                    if table == "market_raw_event":
                        raw_counts[segment_id] += count
                    else:
                        canonical_counts[segment_id] += count
                    hashes[segment_id].add(str(row["segment_content_hash"]))
        if any(
            raw_counts[item.segment_id] != item.raw_count
            or canonical_counts[item.segment_id] != item.canonical_count
            or hashes[item.segment_id] != {item.content_hash}
            for item in segments
        ):
            raise OnlyClickHouseSegmentConflictError("CLICKHOUSE_SEGMENT_NOT_EXACT")

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
            f"AND instrument_id={_quote(scope.instrument_id)} "
            f"AND ts_event_ns{'>' if scope.data_kind == 'BAR' else '>='}{scope.start_ns} "
            f"AND ts_event_ns<={scope.end_ns} ORDER BY ts_event_ns, canonical_fact_id, raw_event_id"
        )
        return tuple(self._decode_fact(scope.data_kind, row) for row in rows)

    def _segment_counts(self, segment_id: str) -> tuple[int, int, int, int]:
        result: list[int] = []
        for table in _SEGMENT_TABLES:
            rows = self._client.query_json(
                f"SELECT count() AS count FROM {table} WHERE segment_id={_quote(segment_id)}"
            )
            result.append(0 if not rows else int(str(rows[0]["count"])))
        return result[0], result[1], result[2], result[3]

    def _segment_hashes(self, segment_id: str) -> set[str]:
        result: set[str] = set()
        for table in _SEGMENT_TABLES:
            rows = self._client.query_json(
                f"SELECT DISTINCT segment_content_hash FROM {table} WHERE segment_id={_quote(segment_id)}"
            )
            result.update(str(row["segment_content_hash"]) for row in rows)
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
        if item.integration_binding_fingerprint is not None:
            # Only stamped rows carry the column so previously written rows keep an
            # identical record_hash and stay verifiable without a rewrite.
            row["integration_binding_fingerprint"] = item.integration_binding_fingerprint
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


__all__ = [name for name in globals() if name.startswith("Only")]
