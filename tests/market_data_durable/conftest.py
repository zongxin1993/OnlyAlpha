from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from onlyalpha.data.enums import OnlyDataSequenceSemantics, OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataSequence, OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.data.identity import only_bar_update_id, only_trade_update_id
from onlyalpha.data.models import OnlyBarUpdate, OnlyMarketDataInboundUpdate, OnlyTradeTickUpdate
from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyOrderSide,
    OnlyPriceType,
    OnlySessionType,
)
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRuntimeId, OnlyTradeId
from onlyalpha.domain.market import OnlyBar, OnlyBarSpecification, OnlyBarType, OnlyTradeTick
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity

SOURCE = OnlyMarketDataSourceId("BINANCE_SPOT")
INSTRUMENT = OnlyInstrumentId.parse("BTCUSDT.BINANCE")
VERSION = OnlyDataVersion("BINANCE_SPOT_V1")
BASE = datetime(2026, 1, 1, tzinfo=UTC)
BAR_TYPE = OnlyBarType(
    INSTRUMENT,
    OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
    OnlyAggregationSource.EXTERNAL,
)


def trade_update(sequence: int = 10, *, price: str = "100.12000000") -> OnlyMarketDataInboundUpdate:
    trade_id = OnlyTradeId(str(sequence))
    event = BASE + timedelta(seconds=sequence)
    trade = OnlyTradeTick(
        INSTRUMENT,
        event,
        event,
        sequence,
        "BINANCE_SPOT",
        OnlyPrice(Decimal(price), 8),
        OnlyQuantity(Decimal("0.01000000"), 8),
        OnlyOrderSide.BUY,
        trade_id,
    )
    return OnlyMarketDataInboundUpdate(
        only_trade_update_id(SOURCE, INSTRUMENT, trade_id, VERSION),
        OnlyRuntimeId("runtime-p93"),
        SOURCE,
        OnlyDataSequence(sequence),
        VERSION,
        INSTRUMENT,
        OnlyMarketDataType.TRADE,
        OnlyTradeTickUpdate(trade),
        OnlyTimestamp.from_datetime(event),
        OnlyTimestamp.from_datetime(event),
        sequence_semantics=OnlyDataSequenceSemantics.CONTIGUOUS,
    )


def bar_update(index: int = 0, *, close: str = "101.00000000") -> OnlyMarketDataInboundUpdate:
    start = BASE + timedelta(minutes=index)
    end = start + timedelta(minutes=1)
    bar = OnlyBar(
        bar_type=BAR_TYPE,
        open=OnlyPrice(Decimal("100.00000000"), 8),
        high=OnlyPrice(Decimal("102.00000000"), 8),
        low=OnlyPrice(Decimal("99.00000000"), 8),
        close=OnlyPrice(Decimal(close), 8),
        volume=OnlyQuantity(Decimal("2.00000000"), 8),
        quote_volume=OnlyQuantity(Decimal("201.0000000000000000"), 16),
        turnover=None,
        trade_count=3,
        open_interest=None,
        bar_start=start,
        bar_end=end,
        ts_event=end,
        ts_init=end,
        is_closed=True,
        revision=0,
        adjustment_type=OnlyAdjustmentType.RAW,
        trading_day=start.date(),
        session_type=OnlySessionType.CONTINUOUS,
    )
    return OnlyMarketDataInboundUpdate(
        only_bar_update_id(SOURCE, INSTRUMENT, BAR_TYPE, start, VERSION),
        OnlyRuntimeId("runtime-p93"),
        SOURCE,
        OnlyDataSequence(int(start.timestamp()) // 60),
        VERSION,
        INSTRUMENT,
        OnlyMarketDataType.BAR,
        OnlyBarUpdate(bar),
        OnlyTimestamp.from_datetime(end),
        OnlyTimestamp.from_datetime(end),
        sequence_semantics=OnlyDataSequenceSemantics.CONTIGUOUS,
    )


@pytest.fixture
def fixed_now():
    return lambda: BASE + timedelta(hours=1)
