from __future__ import annotations

import logging
import threading
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from onlyalpha.application.market_data_stream import (
    OnlyMarketDataStreamEventV1,
    OnlyMarketDataStreamSession,
)
from onlyalpha.core.clock import OnlyVirtualClock
from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.data.evidence import OnlyRawProviderObservation
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
from onlyalpha.market_data.durable import (
    OnlyDurableMarketDataRecorder,
    OnlyInMemoryMarketDataCatalog,
    OnlyInMemoryMarketFactStore,
    OnlyMarketDataDrainService,
    OnlyMarketDataIngress,
    OnlyMarketDataRecoveryCoordinator,
    OnlyMarketDataWal,
    OnlyRevisionCommitService,
)
from onlyalpha.market_data.durable.models import OnlyMarketDataHealth, OnlyRecordingState


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


@pytest.mark.parametrize("sink_fails", [False, True])
def test_stream_logs_authoritative_health_on_degradation_and_recovery(
    caplog: pytest.LogCaptureFixture, sink_fails: bool
) -> None:
    session = _session([])
    health = OnlyMarketDataHealth(OnlyRecordingState.HEALTHY, 0, 1000, 0, 0, None, 0, None, None, 0, None)
    session._drain = SimpleNamespace(health=lambda: health)  # type: ignore[assignment]
    assert session.next_event(0).event == "SUBSCRIBED"  # type: ignore[union-attr]
    session.emit_state("READY")
    assert session.next_event(0).payload == {"state": "READY"}  # type: ignore[union-attr]
    health = replace(
        health,
        recording_state=OnlyRecordingState.DEGRADED,
        sealed_uncommitted_segments=1,
        last_recovery_error="RuntimeError:database unavailable",
    )

    class FailingSink(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            raise RuntimeError("diagnostic sink unavailable")

    logger = logging.getLogger("onlyalpha.market_data.durable.stream")
    handler = FailingSink()
    if sink_fails:
        logger.addHandler(handler)
    try:
        with caplog.at_level("INFO", logger=logger.name):
            assert session.next_event(0).payload == {"state": "DEGRADED"}  # type: ignore[union-attr]
            assert session.next_event(0) is None
            health = replace(
                health,
                recording_state=OnlyRecordingState.HEALTHY,
                sealed_uncommitted_segments=0,
                last_recovery_error=None,
                last_committed_segment="segment",
            )
            assert session.next_event(0).payload == {"state": "READY"}  # type: ignore[union-attr]
    finally:
        if sink_fails:
            logger.removeHandler(handler)
    if sink_fails:
        return
    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 2
    assert '"last_recovery_error": "RuntimeError:database unavailable"' in messages[0]
    assert '"sealed_uncommitted_segments": 1' in messages[0]
    assert '"last_recovery_error": null' in messages[1]
    assert '"last_committed_segment": "segment"' in messages[1]


def _durable_session(tmp_path: Path, store: OnlyInMemoryMarketFactStore):
    def now():
        return datetime(2026, 1, 1, tzinfo=UTC)

    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000, now=now)
    catalog = OnlyInMemoryMarketDataCatalog()
    recovery = OnlyMarketDataRecoveryCoordinator(
        wal, store, catalog, OnlyRevisionCommitService(store, catalog, now=now)
    )
    drain = OnlyMarketDataDrainService(recovery)
    recorder = OnlyDurableMarketDataRecorder(
        OnlyMarketDataIngress(wal, normalizer_id="normalizer", normalizer_version="1", ingest_clock_ns=lambda: 1),
        max_records_per_segment=1,
        on_sealed=drain.submit,
    )
    session = _session([])
    session._drain = drain
    assert session.next_event(0).event == "SUBSCRIBED"  # type: ignore[union-attr]
    session.emit_state("READY")
    assert session.next_event(0).payload == {"state": "READY"}  # type: ignore[union-attr]
    drain.start()
    return session, recorder, drain, catalog


def _raw_preview(index: int) -> OnlyRawProviderObservation:
    return OnlyRawProviderObservation(
        source_id="source",
        capture_session_id="session",
        provider="provider",
        venue="venue",
        market="market",
        stream="kline",
        provider_event_type="kline",
        provider_event_id=str(index),
        ts_receive_ns=index + 1,
        payload=str(index).encode(),
    )


def test_stream_emits_ready_only_after_actual_background_durable_recovery(tmp_path: Path) -> None:
    retry_entered = threading.Event()
    release = threading.Event()
    attempts = 0

    def transient_failure(_stage: str) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("database unavailable")
        if attempts == 2:
            retry_entered.set()
            assert release.wait(5)

    store = OnlyInMemoryMarketFactStore(fault=transient_failure)
    session, recorder, drain, catalog = _durable_session(tmp_path, store)
    try:
        recorder(_raw_preview(0), None)
        assert retry_entered.wait(5)
        assert drain.health().last_recovery_error == "RuntimeError:database unavailable"
        assert drain.health().sealed_uncommitted_segments == 1
        assert session.next_event(0).payload == {"state": "DEGRADED"}  # type: ignore[union-attr]
        session.emit_preview(_preview("1.000000000000000001"))
        assert session.next_event(0).event == "BAR_PREVIEW"  # type: ignore[union-attr]
        assert session.next_event(0) is None  # No synthetic READY while retry remains blocked.
        release.set()
        drain._queue.join()
        assert drain.health().last_recovery_error is None
        assert drain.health().recording_state is OnlyRecordingState.HEALTHY
        assert drain.health().sealed_uncommitted_segments == 0
        assert session.next_event(0).payload == {"state": "READY"}  # type: ignore[union-attr]
        assert len(catalog._segments) == 1
        assert len(store._raw) == 1
        assert drain._worker is not None and drain._worker.is_alive()
    finally:
        release.set()
        drain.stop()


def test_continuous_preview_frames_keep_exact_raw_evidence_and_one_session(tmp_path: Path) -> None:
    store = OnlyInMemoryMarketFactStore()
    session, recorder, drain, catalog = _durable_session(tmp_path, store)
    try:
        for index in range(64):
            recorder(_raw_preview(index), None)
            session.emit_preview(_preview(str(index + 1)))
            assert session.next_event(0).event == "BAR_PREVIEW"  # type: ignore[union-attr]
        drain._queue.join()
        assert drain.health().recording_state is OnlyRecordingState.HEALTHY
        assert drain.health().last_recovery_error is None
        assert drain.health().sealed_uncommitted_segments == 0
        assert len(catalog._segments) == 64
        assert len(store._raw) == 64
        assert all(store.inspect_segment(segment) == "EXACT" for segment in catalog._segments.values())
        assert session._subscription_id == "subscription"
        assert session.next_event(0) is None
    finally:
        drain.stop()


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
