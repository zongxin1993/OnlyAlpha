from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace

from onlyalpha.application.market_data_stream import (
    OnlyMarketDataStreamEventV1,
    OnlyMarketDataStreamSession,
)
from onlyalpha.core.clock import OnlyVirtualClock
from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataSequence, OnlyDataVersion, OnlyMarketDataSourceId, OnlyMarketDataUpdateId
from onlyalpha.data.models import OnlyBarUpdate, OnlyMarketDataInboundUpdate, OnlyRealtimeBarPreviewV1
from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlySessionType,
)
from onlyalpha.domain.identifiers import OnlyCalendarId, OnlyInstrumentId, OnlyRuntimeId, OnlyVenueId
from onlyalpha.domain.market import OnlyBar, OnlyBarSemantic, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp, OnlyTimeZone
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.market_data.aggregation.time_bar import OnlyTimeBarAggregator


def _preview(close: str, minute: int = 1) -> OnlyRealtimeBarPreviewV1:
    instrument = OnlyInstrumentId.parse("BTCUSDT.BINANCE")
    return OnlyRealtimeBarPreviewV1(
        OnlyMarketDataSourceId("binance.spot.market_data.us"),
        instrument,
        OnlyBarType(instrument, OnlyBarSemantic.fixed_duration(1)),
        minute * 60_000_000_000,
        (minute + 1) * 60_000_000_000,
        "1",
        "2",
        "0.5",
        close,
        "10",
        (minute * 60 + 30) * 1_000_000_000,
        (minute * 60 + 30) * 1_000_000_000,
    )


def _session(events: list[str], *, capacity: int = 2, **projection: object) -> OnlyMarketDataStreamSession:
    source = SimpleNamespace(
        unsubscribe=lambda _request: events.append("unsubscribe"),
        stop=lambda: events.append("stop"),
    )
    recorder = SimpleNamespace(close=lambda: events.append("recorder"))
    drain = SimpleNamespace(stop=lambda: events.append("drain"))
    recovery = SimpleNamespace(recover_all=lambda: events.append("recovery"))
    session = OnlyMarketDataStreamSession(
        stream_id="stream",
        source_id="source",
        instrument_id="BTCUSDT.BINANCE",
        source=source,  # type: ignore[arg-type]
        subscription_id="subscription",
        recorder=recorder,  # type: ignore[arg-type]
        drain=drain,  # type: ignore[arg-type]
        recovery=recovery,  # type: ignore[arg-type]
        reliable_capacity=capacity,
        on_close=lambda _stream_id: events.append("release"),
        **projection,
    )
    session.activate(OnlyMarketDataStreamEventV1("SUBSCRIBED", {}))
    return session


def test_preview_coalesces_but_reliable_events_remain_fifo() -> None:
    session = _session([])
    session.emit_preview(_preview("1"))
    session.emit_preview(_preview("2"))
    session.emit_reliable(OnlyMarketDataStreamEventV1("STATE", {"state": "READY"}))

    assert session.next_event(0).event == "SUBSCRIBED"  # type: ignore[union-attr]
    assert session.next_event(0).event == "STATE"  # type: ignore[union-attr]
    preview = session.next_event(0)
    assert preview is not None and preview.payload["bar"]["close"] == "2"  # type: ignore[index]


def test_reliable_overflow_fails_explicitly_and_close_is_idempotent() -> None:
    events: list[str] = []
    session = _session(events, capacity=1)
    session.emit_reliable(OnlyMarketDataStreamEventV1("BAR_CLOSED", {}))
    session.emit_reliable(OnlyMarketDataStreamEventV1("BAR_CLOSED", {}))

    assert session.next_event(0).event == "SUBSCRIBED"  # type: ignore[union-attr]
    terminal = session.next_event(0)
    assert terminal is not None and terminal.event == "ERROR"
    session.close()
    session.close()
    assert events == ["unsubscribe", "stop", "recorder", "drain", "recovery", "release"]


def test_derived_stream_emits_base_cursor_preview_and_seven_minute_close() -> None:
    instrument = OnlyInstrumentId.parse("BTCUSDT.BINANCE")
    source = OnlyMarketDataSourceId("binance.spot.market_data.us")
    base = OnlyBarType(instrument, OnlyBarSemantic.fixed_duration(1))
    target = OnlyBarType(instrument, OnlyBarSemantic.fixed_duration(7))
    calendar = OnlyTradingCalendar(
        OnlyCalendarId("TEST-24X7"),
        OnlyVenueId("BINANCE"),
        OnlyTimeZone("UTC"),
        (OnlyTradingSession("continuous", time(0), time(0), OnlySessionType.CONTINUOUS),),
        weekend_days=(),
    )
    aggregator = OnlyTimeBarAggregator(base, target, calendar, OnlyVirtualClock(datetime(1970, 1, 1, 1, tzinfo=UTC)))
    session = _session(
        [],
        capacity=20,
        aggregator=aggregator,
        instrument=SimpleNamespace(price_precision=2, quantity_precision=0),
        calendar=calendar,
    )
    assert session.next_event(0).event == "SUBSCRIBED"  # type: ignore[union-attr]

    def update(minute: int) -> OnlyMarketDataInboundUpdate:
        start = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(minutes=minute)
        end = start + timedelta(minutes=1)
        bar = OnlyBar(
            bar_type=base,
            open=OnlyPrice(Decimal("1.00"), 2),
            high=OnlyPrice(Decimal("2.00"), 2),
            low=OnlyPrice(Decimal("0.50"), 2),
            close=OnlyPrice(Decimal("1.50"), 2),
            volume=OnlyQuantity(Decimal("10"), 0),
            quote_volume=None,
            turnover=None,
            trade_count=1,
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
            OnlyMarketDataUpdateId(f"bar-{minute}"),
            OnlyRuntimeId("stream"),
            source,
            OnlyDataSequence(minute),
            OnlyDataVersion("v1"),
            instrument,
            OnlyMarketDataType.BAR,
            OnlyBarUpdate(bar),
            OnlyTimestamp.from_datetime(end),
            OnlyTimestamp.from_datetime(end),
        )

    session.emit_closed(update(0))
    assert session.next_event(0).event == "BASE_CURSOR"  # type: ignore[union-attr]
    forming = _preview("1.75")
    session.emit_preview(replace(forming, ts_receive_ns=forming.ts_event_ns - 4_000_000_000))
    preview = session.next_event(0)
    assert preview is not None and preview.event == "BAR_PREVIEW"
    assert preview.payload["bar_semantic"] == target.semantic.to_dict()
    assert preview.payload["bar"]["volume"] == "20"  # type: ignore[index]
    for minute in range(1, 7):
        session.emit_closed(update(minute))
    messages = [session.next_event(0) for _ in range(7)]
    assert [item.event for item in messages if item is not None].count("BAR_CLOSED") == 1
    closed = messages[-1]
    assert closed is not None and closed.payload["bar"]["closed"] is True  # type: ignore[index]
    session.emit_preview(_preview("1.75", 7))
    next_preview = session.next_event(0)
    assert next_preview is not None and next_preview.event == "BAR_PREVIEW"
    assert next_preview.payload["bar"]["bar_start_ns"] == "420000000000"  # type: ignore[index]
    assert next_preview.payload["bar"]["volume"] == "10"  # type: ignore[index]
