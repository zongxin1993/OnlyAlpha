"""Opt-in acceptance against a running local MiniQMT historical service."""

import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from onlyalpha_plugin_miniqmt.historical_worker.client import OnlyMiniQmtHistoricalIsolatedClient

from onlyalpha.data.identifiers import OnlyDataVersion
from onlyalpha.data.warmup import OnlyHistoricalWarmupRequest, OnlyHistoricalWarmupStatus
from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyPriceType,
)
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.domain.market import OnlyBarSpecification, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp

pytestmark = [
    pytest.mark.external,
    pytest.mark.miniqmt,
    pytest.mark.requires_local_qmt,
    pytest.mark.windows,
    pytest.mark.skipif(
        os.environ.get("ONLYALPHA_MINIQMT_REAL_HISTORY") != "1",
        reason="requires a running, read-only MiniQMT data service",
    ),
]


def test_real_history_is_isolated_and_returns_fifty_closed_bars(tmp_path: Path) -> None:
    instrument = OnlyInstrumentId.parse(os.environ.get("ONLYALPHA_MINIQMT_SYMBOL", "600000.XSHG"))
    bar_type = OnlyBarType(
        instrument,
        OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
        OnlyAggregationSource.EXTERNAL,
    )
    end = datetime.fromisoformat(os.environ.get("ONLYALPHA_MINIQMT_END", "2026-08-03T02:00:00+00:00"))
    request = OnlyHistoricalWarmupRequest(
        "real-history-read-only",
        OnlyRuntimeId("real-history-verification"),
        instrument,
        bar_type,
        50,
        OnlyTimestamp.from_datetime(end.astimezone(UTC)),
        OnlyDataVersion("miniqmt-real-read-only"),
        OnlyAdjustmentType.RAW,
        30,
        "miniqmt-history-v1",
    )
    userdata = Path(
        os.environ.get("userdata_mini_path")
        or os.environ.get("ONLYALPHA_MINIQMT_PATH")
        or r"C:\国金证券QMT交易端\userdata_mini"
    )
    create_request = SimpleNamespace(instruments={instrument: SimpleNamespace(price_precision=2, quantity_precision=0)})

    result = OnlyMiniQmtHistoricalIsolatedClient(
        create_request,
        userdata,
        tmp_path / "runtime_state" / "warmup",
    ).load_warmup(request)

    assert result.status is OnlyHistoricalWarmupStatus.SUCCESS, result.diagnostic
    assert len(result.bars) == 50
    assert tuple(item.bar_end for item in result.bars) == tuple(sorted(item.bar_end for item in result.bars))
    assert len({(item.instrument_id, item.bar_type, item.bar_start) for item in result.bars}) == 50
    assert all(item.is_closed and item.bar_end <= end for item in result.bars)
    assert result.last_bar_end == OnlyTimestamp.from_datetime(result.bars[-1].bar_end)
