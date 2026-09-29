from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from onlyalpha.market_data.durable import OnlyIngestSegment, OnlyMarketDataProvenance, OnlyMarketDataScope
from onlyalpha.persistence.clickhouse import OnlyClickHouseMarketFactStore, OnlyClickHouseSegmentConflictError


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
