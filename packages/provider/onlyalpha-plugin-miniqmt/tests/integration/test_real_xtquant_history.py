"""Opt-in, read-only validation against a running MiniQMT data service."""

import os
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from onlyalpha_plugin_miniqmt.data_source.historical import load_bars
from onlyalpha_plugin_miniqmt.sdk.loader import load_xtquant

from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.data.models import OnlyHistoricalBarRequest, OnlyHistoricalDataRange
from onlyalpha.domain.enums import (
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyPriceType,
)
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.domain.market import OnlyBarSpecification, OnlyBarType

pytestmark = pytest.mark.skipif(
    os.environ.get("ONLYALPHA_MINIQMT_REAL_HISTORY") != "1",
    reason="requires a running, read-only MiniQMT data service",
)


def test_real_history_converts_to_onlyalpha_bars() -> None:
    instrument = OnlyInstrumentId.parse(os.environ.get("ONLYALPHA_MINIQMT_SYMBOL", "600000.XSHG"))
    bar_type = OnlyBarType(
        instrument,
        OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
        OnlyAggregationSource.EXTERNAL,
    )
    start = datetime.fromisoformat(os.environ.get("ONLYALPHA_MINIQMT_START", "2026-07-17T01:30:00+00:00"))
    end = datetime.fromisoformat(os.environ.get("ONLYALPHA_MINIQMT_END", "2026-07-17T02:01:00+00:00"))
    request = OnlyHistoricalBarRequest(
        "real-history-read-only",
        frozenset({instrument}),
        frozenset({bar_type}),
        OnlyHistoricalDataRange(start.astimezone(UTC), end.astimezone(UTC)),
        OnlyDataVersion("miniqmt-real-read-only"),
    )
    create_request = SimpleNamespace(
        runtime_id=OnlyRuntimeId("real-history-verification"),
        source_id=OnlyMarketDataSourceId("miniqmt"),
    )

    records = load_bars(load_xtquant().xtdata, create_request, request)

    assert records
    assert tuple(item.ts_event for item in records) == tuple(sorted(item.ts_event for item in records))
    assert len({item.ts_event for item in records}) == len(records)
    assert all(item.payload.bar.ts_event.tzinfo is UTC for item in records)
    assert all(start <= item.payload.bar.ts_event < end for item in records)
