from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from onlyalpha.market_data.durable import (
    OnlyIngestSegment,
    OnlyMarketDataIngress,
    OnlyMarketDataProvenance,
    OnlyMarketDataScope,
    OnlyMarketDataWal,
)
from onlyalpha.persistence.clickhouse import OnlyClickHouseMarketFactStore, OnlyClickHouseSegmentConflictError

from .conftest import BAR_CONSTRUCTION, BAR_TYPE_ID, BASE, INSTRUMENT, bar_update
from .test_recovery_revision_dataset import _observation


class _EvidenceClient:
    def __init__(self, rows: dict[str, dict[str, list[str]]]) -> None:
        self.rows = rows
        self.queries: list[str] = []

    def query_json(self, sql: str, *, database: str | None = None) -> tuple[dict[str, object], ...]:
        del database
        self.queries.append(sql)
        if sql == "SELECT version() AS version":
            return ({"version": "26.3.1.1"},)
        table = re.search(r"FROM (market_[a-z_]+)", sql)
        assert table is not None
        stored = self.rows[table.group(1)]
        ids = re.findall(r"'([^']+)'", sql.split("WHERE segment_id", 1)[1].split(" GROUP BY", 1)[0])
        if "GROUP BY segment_id, segment_content_hash" in sql:
            return tuple(
                {
                    "segment_id": segment_id,
                    "segment_content_hash": content_hash,
                    "physical_count": hashes.count(content_hash),
                }
                for segment_id in ids
                for hashes in (stored.get(segment_id, []),)
                for content_hash in sorted(set(hashes))
            )
        segment_id = ids[0]
        hashes = stored.get(segment_id, [])
        if "count() AS count" in sql:
            return ({"count": len(hashes)},)
        if "SELECT DISTINCT segment_content_hash" in sql:
            return tuple({"segment_content_hash": item} for item in sorted(set(hashes)))
        return ()


class _BatchClient:
    def __init__(self) -> None:
        self.rows: dict[str, list[dict[str, object]]] = {
            "market_raw_event": [],
            "market_trade": [],
            "market_bar": [],
            "market_reference_price": [],
        }
        self.queries: list[str] = []
        self.inserts = 0
        self.unexpected: tuple[str, dict[str, object]] | None = None

    def query_json(self, sql: str, *, database: str | None = None) -> tuple[dict[str, object], ...]:
        del database
        self.queries.append(sql)
        if sql == "SELECT version() AS version":
            return ({"version": "26.3.1.1"},)
        table_match = re.search(r"FROM (market_[a-z_]+)", sql)
        assert table_match is not None
        table = table_match.group(1)
        ids = set(re.findall(r"'([^']+)'", sql.split("WHERE segment_id", 1)[1].split(" GROUP BY", 1)[0]))
        identities = ("raw_event_id",) if table == "market_raw_event" else ("canonical_fact_id", "raw_event_id")
        selected = [row for row in self.rows[table] if str(row["segment_id"]) in ids]
        if self.unexpected is not None and self.unexpected[0] == table:
            selected.append(self.unexpected[1])
        grouped: dict[tuple[object, ...], int] = {}
        for row in selected:
            key = (
                row["segment_id"],
                *(row[item] for item in identities),
                row["record_hash"],
                row["segment_content_hash"],
            )
            grouped[key] = grouped.get(key, 0) + 1
        return tuple(
            {
                "segment_id": key[0],
                **{name: key[index + 1] for index, name in enumerate(identities)},
                "record_hash": key[-2],
                "segment_content_hash": key[-1],
                "physical_count": count,
            }
            for key, count in grouped.items()
        )

    def insert_json_each_row(self, table: str, rows) -> None:  # type: ignore[no-untyped-def]
        self.inserts += 1
        self.rows[table].extend(dict(row) for row in rows)


def _batch(tmp_path: Path, fixed_now, count: int):  # type: ignore[no-untyped-def]
    segments = []
    records_by_segment = {}
    for index in range(count):
        wal = OnlyMarketDataWal(tmp_path / str(index), capacity_bytes=1_000_000, now=fixed_now)
        ingress = OnlyMarketDataIngress(
            wal,
            normalizer_id="test",
            normalizer_version="1",
            ingest_clock_ns=lambda: 5,
            bar_construction=BAR_CONSTRUCTION,
        )
        ingress.begin_segment(f"batch-{index}")
        ingress.record(_observation(index), bar_update(index))
        segment = ingress.seal()
        segments.append(segment)
        records_by_segment[segment.segment_id] = wal.read_sealed(segment.segment_id)
    base_ns = int(BASE.timestamp() * 1_000_000_000)
    scope = OnlyMarketDataScope(
        "BINANCE_SPOT",
        "SPOT",
        str(INSTRUMENT),
        "BAR",
        base_ns,
        base_ns + count * 60_000_000_000,
        "BINANCE_SPOT_V1",
        BAR_TYPE_ID,
        bar_construction=BAR_CONSTRUCTION,
    )
    return tuple(segments), records_by_segment, scope


def _segments(count: int) -> tuple[OnlyIngestSegment, ...]:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return tuple(
        OnlyIngestSegment(
            f"segment-{index}",
            "capture",
            "source",
            "SPOT",
            "/klines",
            "provider",
            "venue",
            OnlyMarketDataProvenance.REST_BACKFILL,
            "schema",
            "json",
            1,
            1,
            1,
            0,
            f"{index:064x}",
            now,
            now,
        )
        for index in range(count)
    )


def _rows(segments: tuple[OnlyIngestSegment, ...]) -> dict[str, dict[str, list[str]]]:
    return {
        "market_raw_event": {item.segment_id: [item.content_hash] for item in segments},
        "market_trade": {},
        "market_bar": {},
        "market_reference_price": {},
    }


def _read_query_count(segment_count: int) -> int:
    segments = _segments(segment_count)
    client = _EvidenceClient(_rows(segments))
    store = OnlyClickHouseMarketFactStore(client)  # type: ignore[arg-type]
    scope = OnlyMarketDataScope("source", "SPOT", "instrument", "BAR", 0, 1, "v1", None)
    assert store.read_segment_facts(segments, scope) == ()
    return len(client.queries)


def test_exact_segment_read_uses_bounded_batch_queries() -> None:
    ten = _read_query_count(10)
    hundred = _read_query_count(100)
    assert hundred <= 7
    assert hundred == ten


@pytest.mark.parametrize(
    ("case", "mutate"),
    (
        ("missing Segment", lambda rows, segment: rows["market_raw_event"].pop(segment.segment_id)),
        ("wrong raw count", lambda rows, segment: None),
        (
            "wrong canonical count",
            lambda rows, segment: rows["market_bar"].__setitem__(segment.segment_id, [segment.content_hash]),
        ),
        (
            "different segment_content_hash",
            lambda rows, segment: rows["market_raw_event"].__setitem__(segment.segment_id, ["f" * 64]),
        ),
        (
            "two hashes for one Segment",
            lambda rows, segment: rows["market_raw_event"].__setitem__(
                segment.segment_id, [segment.content_hash, "f" * 64]
            ),
        ),
        (
            "extra physical duplicate",
            lambda rows, segment: rows["market_raw_event"][segment.segment_id].append(segment.content_hash),
        ),
    ),
)
def test_batched_exact_segment_read_fails_closed(
    case: str,
    mutate: Callable[[dict[str, dict[str, list[str]]], OnlyIngestSegment], object],
) -> None:
    [segment] = _segments(1)
    rows = _rows((segment,))
    if case == "wrong raw count":
        segment = replace(segment, record_count=2, raw_count=2)
    else:
        mutate(rows, segment)
    store = OnlyClickHouseMarketFactStore(_EvidenceClient(rows))  # type: ignore[arg-type]
    scope = OnlyMarketDataScope("source", "SPOT", "instrument", "BAR", 0, 1, "v1", None)
    with pytest.raises(OnlyClickHouseSegmentConflictError, match="CLICKHOUSE_SEGMENT_NOT_EXACT"):
        store.read_segment_facts((segment,), scope)


def test_batch_write_and_verify_query_count_is_bounded_by_tables_not_segments(tmp_path: Path, fixed_now) -> None:
    counts = []
    for count in (10, 100):
        segments, records, scope = _batch(tmp_path / str(count), fixed_now, count)
        client = _BatchClient()
        store = OnlyClickHouseMarketFactStore(client)  # type: ignore[arg-type]
        client.queries.clear()
        store.write_segments(segments, records)
        store.verify_segments(segments, records, scope)
        counts.append(len(client.queries))
        assert len(client.queries) <= 2 * 4

        client.queries.clear()
        client.inserts = 0
        store.write_segments(segments, records)
        store.verify_segments(segments, records, scope)
        assert len(client.queries) <= 2 * 4
        assert client.inserts == 0
    assert counts[0] == counts[1]


@pytest.mark.parametrize(
    "case",
    (
        "missing raw row",
        "missing canonical row",
        "wrong raw count",
        "wrong canonical count",
        "wrong segment_content_hash",
        "two Segment hashes",
        "wrong record_hash",
        "two hashes for one identity",
        "extra physical duplicate",
        "unexpected Segment ID",
        "mixed EXACT and PARTIAL batch",
    ),
)
def test_batch_exact_verification_failure_matrix(tmp_path: Path, fixed_now, case: str) -> None:
    count = 2 if case == "mixed EXACT and PARTIAL batch" else 1
    segments, records, scope = _batch(tmp_path / case.replace(" ", "-"), fixed_now, count)
    client = _BatchClient()
    store = OnlyClickHouseMarketFactStore(client)  # type: ignore[arg-type]
    store.write_segments(segments, records)
    raw = client.rows["market_raw_event"]
    canonical = client.rows["market_bar"]
    if case == "missing raw row":
        raw.pop()
    elif case == "missing canonical row":
        canonical.pop()
    elif case in {"wrong raw count", "extra physical duplicate"}:
        raw.append(dict(raw[0]))
    elif case == "wrong canonical count":
        canonical.append(dict(canonical[0]))
    elif case == "wrong segment_content_hash":
        raw[0]["segment_content_hash"] = "f" * 64
    elif case == "two Segment hashes":
        duplicate = dict(raw[0])
        duplicate["segment_content_hash"] = "f" * 64
        raw.append(duplicate)
    elif case == "wrong record_hash":
        raw[0]["record_hash"] = "f" * 64
    elif case == "two hashes for one identity":
        duplicate = dict(raw[0])
        duplicate["record_hash"] = "f" * 64
        raw.append(duplicate)
    elif case == "unexpected Segment ID":
        unexpected = dict(raw[0])
        unexpected["segment_id"] = "unexpected"
        client.unexpected = ("market_raw_event", unexpected)
    elif case == "mixed EXACT and PARTIAL batch":
        raw[:] = [row for row in raw if row["segment_id"] != segments[-1].segment_id]
    else:  # pragma: no cover - exhaustive parametrization
        raise AssertionError(case)

    with pytest.raises(OnlyClickHouseSegmentConflictError, match="CLICKHOUSE"):
        store.verify_segments(segments, records, scope)
