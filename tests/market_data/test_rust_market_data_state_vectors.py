"""Common valid semantics; no schema-2/Python or whole-module parity claim."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from onlyalpha.domain.identifiers import OnlyClusterId, OnlyRuntimeId
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.market_data.cache import OnlyMarketDataCache
from onlyalpha.market_data.snapshot import OnlyBarSnapshot, OnlyMarketDataSnapshot

DATA = Path(__file__).resolve().parents[2] / "test-data/market-data-state"


def kind(instrument: str, window: int) -> OnlyBarType:
    symbol, venue = instrument.rsplit(".", 1)
    return OnlyBarType.from_dict(
        {
            "schema_version": 2,
            "instrument_id": {
                "schema_version": 1,
                "symbol": {"schema_version": 1, "value": symbol},
                "venue": {"schema_version": 1, "value": venue},
            },
            "semantic": {
                "schema_version": 3,
                "formation": {
                    "schema_version": 1,
                    "kind": "FIXED_DURATION",
                    "window_minutes": window,
                    "stride_minutes": window,
                    "alignment": "UTC",
                },
                "price_type": "LAST",
                "adjustment_policy": "RAW",
            },
        }
    )


def bar(instrument: str, window: int, end: int) -> OnlyBar:
    def price(value: str) -> dict[str, object]:
        return {"schema_version": 1, "value": value, "precision": 2}

    def time(minute: int) -> str:
        return f"2026-01-05T01:{30 + minute:02}:00Z"

    return OnlyBar.from_dict(
        {
            "schema_version": 1,
            "bar_type": kind(instrument, window).to_record(),
            "open": price("10.00"),
            "high": price("10.10"),
            "low": price("9.90"),
            "close": price("10.05"),
            "volume": {"schema_version": 1, "value": "100", "precision": 0},
            "quote_volume": None,
            "turnover": None,
            "trade_count": 1,
            "open_interest": None,
            "bar_start": time(end - window),
            "bar_end": time(end),
            "ts_event": time(end),
            "ts_init": time(end),
            "is_closed": True,
            "revision": 0,
            "adjustment_type": "RAW",
            "trading_day": "2026-01-05",
            "session_type": "CONTINUOUS",
        }
    )


@pytest.mark.parametrize(
    "row",
    [json.loads(line) for line in (DATA / "operations-v1.jsonl").read_text().splitlines()],
    ids=lambda row: row["id"],
)
def test_common_valid_operations(row: dict) -> None:
    cache = OnlyMarketDataCache(row["history_limit"])
    snapshot = None
    for operation in row["operations"]:
        if "restore" in operation:
            cache.restore_checkpoint(cache.capture_checkpoint())
        elif "seed_version" in operation:
            checkpoint = cache.capture_checkpoint()
            target = kind(*operation["kind"])
            for entry in checkpoint["versions"]:
                if OnlyBarType.from_json(entry[0]) == target:
                    entry[1] = operation["seed_version"]
            cache.restore_checkpoint(checkpoint)
        else:
            bars = [bar(*item) for item in operation["bars"]]
            for item in bars:
                cache.update_closed(item)
            primary_type = kind(*operation["primary"])
            primary = cache.latest_closed(primary_type)
            assert primary is not None
            snapshot = OnlyMarketDataSnapshot(
                ts_event=OnlyTimestamp.from_datetime(primary.bar_end),
                ts_init=OnlyTimestamp.from_datetime(primary.bar_end),
                runtime_id=OnlyRuntimeId("runtime"),
                cluster_id=None,
                instrument_id=primary.instrument_id,
                primary_bar_type=primary_type,
                primary_bar=primary,
                updated_bar_types=frozenset(item.bar_type for item in bars),
                bars=OnlyBarSnapshot(cache.latest_all(), cache.histories_all(), {}, cache.versions_all()),
                indicator_values={},
                indicator_versions={},
                trading_day=primary.trading_day,
                session_type=primary.session_type,
            )
    for instrument, window, ends, version in row["expected"]:
        target = kind(instrument, window)
        expected = tuple(bar(instrument, window, end) for end in ends)
        assert cache.history(target, 99) == expected
        assert cache.version(target) == version
        assert cache.latest_closed(target) == (expected[-1] if expected else None)
        assert cache.current_partial(target) is None
    if "filter" in row:
        assert snapshot is not None
        allowed = tuple(kind(*item) for item in row["filter"])
        view = snapshot.restrict(
            cluster_id=OnlyClusterId("c"), bar_types=allowed, primary_bar_type=kind(*row["primary"])
        )
        end = datetime(2026, 1, 5, 1, 30, tzinfo=UTC) + timedelta(minutes=row["event_minute"])
        assert view.ts_event == OnlyTimestamp.from_datetime(end)
        for target in allowed:
            assert view.history(target, 99) == cache.history(target, 99)
            assert view.data_versions.get(target, 0) == cache.version(target)
        assert set(view.bars.histories) <= set(allowed)


def test_domain_facts_in_independent_schema2_vectors() -> None:
    for line in (DATA / "records-v2.jsonl").read_text().splitlines():
        row = json.loads(line)
        for series in row["record"]["series"]:
            for record in series["history"]:
                assert OnlyBar.from_dict(record).to_record() == record
