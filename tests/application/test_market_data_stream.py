from __future__ import annotations

from types import SimpleNamespace

from onlyalpha.application.market_data_stream import (
    OnlyMarketDataStreamEventV1,
    OnlyMarketDataStreamSession,
)
from onlyalpha.data.identifiers import OnlyMarketDataSourceId
from onlyalpha.data.models import OnlyRealtimeBarPreviewV1
from onlyalpha.domain.enums import OnlyAggregationSource, OnlyBarAggregation, OnlyPriceType
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBarSpecification, OnlyBarType


def _preview(close: str) -> OnlyRealtimeBarPreviewV1:
    instrument = OnlyInstrumentId.parse("BTCUSDT.BINANCE")
    return OnlyRealtimeBarPreviewV1(
        OnlyMarketDataSourceId("binance.spot.market_data.us"),
        instrument,
        OnlyBarType(
            instrument,
            OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
            OnlyAggregationSource.EXTERNAL,
        ),
        60_000_000_000,
        120_000_000_000,
        "1",
        "2",
        "0.5",
        close,
        "10",
        1,
        2,
    )


def _session(events: list[str], *, capacity: int = 2) -> OnlyMarketDataStreamSession:
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
