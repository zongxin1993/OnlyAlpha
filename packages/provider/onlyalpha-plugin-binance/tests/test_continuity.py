import threading
from dataclasses import replace

import pytest
from onlyalpha_plugin_binance.errors import OnlyBinanceError
from onlyalpha_plugin_binance.spot.data_source.continuity import OnlyBinanceSpotContinuityCoordinator
from onlyalpha_plugin_binance.spot.data_source.normalize import only_normalize_rest_kline, only_normalize_rest_trade

from onlyalpha.data.enums import OnlyDataSequenceSemantics, OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataSequence, OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.data.identity import only_bar_update_id, only_trade_update_id
from onlyalpha.data.models import OnlyBarUpdate, OnlyMarketDataInboundUpdate, OnlyTradeTickUpdate
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp


def bar_update(sequence: int, instrument_bar_type) -> OnlyMarketDataInboundUpdate:  # type: ignore[no-untyped-def]
    instrument, bar_type = instrument_bar_type
    start_ms = sequence * 60_000
    bar = only_normalize_rest_kline(
        [
            start_ms,
            "10.00",
            "11.00",
            "9.00",
            "10.50",
            "100",
            start_ms + 59_999,
            "1050",
            42,
            "0",
            "0",
        ],
        instrument,
        bar_type,
    )
    source = OnlyMarketDataSourceId("binance")
    version = OnlyDataVersion("binance-v1")
    timestamp = OnlyTimestamp.from_datetime(bar.ts_event)
    return OnlyMarketDataInboundUpdate(
        only_bar_update_id(source, instrument.instrument_id, bar_type, bar.bar_start, version),
        OnlyRuntimeId("runtime"),
        source,
        OnlyDataSequence(sequence),
        version,
        instrument.instrument_id,
        OnlyMarketDataType.BAR,
        OnlyBarUpdate(bar),
        timestamp,
        timestamp,
        sequence_semantics=OnlyDataSequenceSemantics.CONTIGUOUS,
    )


def trade_update(sequence: int, instrument_bar_type) -> OnlyMarketDataInboundUpdate:  # type: ignore[no-untyped-def]
    instrument, _ = instrument_bar_type
    trade = only_normalize_rest_trade(
        {
            "id": sequence,
            "price": "10.00",
            "qty": "1",
            "time": 1_767_225_600_000 + sequence,
            "isBuyerMaker": False,
        },
        instrument,
    )
    source = OnlyMarketDataSourceId("binance")
    version = OnlyDataVersion("binance-v1")
    timestamp = OnlyTimestamp.from_datetime(trade.ts_event)
    return OnlyMarketDataInboundUpdate(
        only_trade_update_id(source, instrument.instrument_id, trade.trade_id, version),
        OnlyRuntimeId("runtime"),
        source,
        OnlyDataSequence(sequence),
        version,
        instrument.instrument_id,
        OnlyMarketDataType.TRADE,
        OnlyTradeTickUpdate(trade),
        timestamp,
        timestamp,
        sequence_semantics=OnlyDataSequenceSemantics.CONTIGUOUS,
    )


def test_exact_gap_recovery_publishes_stable_order_and_returns_ready(binance_bar_type) -> None:  # type: ignore[no-untyped-def]
    coordinator = OnlyBinanceSpotContinuityCoordinator(10)
    coordinator.connected()
    coordinator.subscription_established()
    coordinator.begin_recovery()
    coordinator.accept_baseline(bar_update(100, binance_bar_type))
    assert coordinator.complete_recovery() == ()

    incoming = bar_update(103, binance_bar_type)

    def recover(update, first: int, last: int):  # type: ignore[no-untyped-def]
        assert update == incoming
        assert (first, last) == (101, 102)
        return tuple(bar_update(item, binance_bar_type) for item in range(first, last + 1))

    accepted = coordinator.accept(incoming, recover)
    assert tuple(int(item.source_sequence) for item in accepted) == (101, 102, 103)
    assert coordinator.state.value == "READY"


def test_unproven_recovery_remains_not_ready_and_buffer_overflow_fails_closed(binance_bar_type) -> None:  # type: ignore[no-untyped-def]
    coordinator = OnlyBinanceSpotContinuityCoordinator(1)
    coordinator.connected()
    coordinator.subscription_established()
    coordinator.begin_recovery()
    coordinator.accept_baseline(bar_update(100, binance_bar_type))
    coordinator.complete_recovery()

    assert coordinator.accept(bar_update(103, binance_bar_type)) == ()
    assert coordinator.state.value == "RECOVERING"
    with pytest.raises(OnlyBinanceError, match="RECOVERY_BUFFER_OVERFLOW"):
        coordinator.buffer(replace(bar_update(104, binance_bar_type), source_sequence=OnlyDataSequence(104)))
    assert coordinator.state.value == "FAILED"


def test_trade_gap_recovery_duplicate_and_out_of_order_converge(binance_bar_type) -> None:  # type: ignore[no-untyped-def]
    coordinator = OnlyBinanceSpotContinuityCoordinator(10)
    coordinator.connected()
    coordinator.subscription_established()
    coordinator.begin_recovery()
    coordinator.accept_baseline(trade_update(100, binance_bar_type))
    coordinator.complete_recovery()

    incoming = trade_update(103, binance_bar_type)
    accepted = coordinator.accept(
        incoming,
        lambda update, first, last: tuple(trade_update(item, binance_bar_type) for item in range(first, last + 1)),
    )
    assert tuple(int(item.source_sequence) for item in accepted) == (101, 102, 103)
    assert coordinator.accept(incoming) == ()
    assert coordinator.accept(trade_update(99, binance_bar_type)) == ()
    assert coordinator.state.value == "READY"


def test_disconnect_immediately_invalidates_ready(binance_bar_type) -> None:  # type: ignore[no-untyped-def]
    coordinator = OnlyBinanceSpotContinuityCoordinator(10)
    coordinator.connected()
    coordinator.subscription_established()
    coordinator.begin_recovery()
    coordinator.accept_baseline(bar_update(100, binance_bar_type))
    coordinator.complete_recovery()

    coordinator.disconnected()

    assert coordinator.state.value == "DISCONNECTED"


def test_ready_cutover_serializes_realtime_fact_and_empties_buffer(binance_bar_type) -> None:  # type: ignore[no-untyped-def]
    coordinator = OnlyBinanceSpotContinuityCoordinator(10)
    coordinator.connected()
    coordinator.subscription_established()
    coordinator.begin_recovery()
    coordinator.accept_baseline(bar_update(100, binance_bar_type))
    coordinator.complete_recovery()
    coordinator.begin_recovery()
    coordinator.accept(bar_update(103, binance_bar_type))
    recovery_entered = threading.Event()
    release_recovery = threading.Event()
    accepted: list[OnlyMarketDataInboundUpdate] = []

    def recover(update, first: int, last: int):  # type: ignore[no-untyped-def]
        recovery_entered.set()
        assert release_recovery.wait(timeout=2)
        return tuple(bar_update(item, binance_bar_type) for item in range(first, last + 1))

    cutover = threading.Thread(target=lambda: accepted.extend(coordinator.complete_recovery(recover)))
    cutover.start()
    assert recovery_entered.wait(timeout=2)
    realtime = threading.Thread(
        target=lambda: accepted.extend(coordinator.accept(bar_update(104, binance_bar_type), recover))
    )
    realtime.start()
    release_recovery.set()
    cutover.join(timeout=2)
    realtime.join(timeout=2)

    assert not cutover.is_alive() and not realtime.is_alive()
    assert tuple(int(item.source_sequence) for item in accepted) == (101, 102, 103, 104)
    assert coordinator.state.value == "READY"
    assert coordinator.buffered_count == 0


def test_recovery_and_realtime_interleavings_converge(binance_bar_type) -> None:  # type: ignore[no-untyped-def]
    def coordinator() -> OnlyBinanceSpotContinuityCoordinator:
        value = OnlyBinanceSpotContinuityCoordinator(10)
        value.connected()
        value.subscription_established()
        value.begin_recovery()
        value.accept_baseline(bar_update(100, binance_bar_type))
        value.complete_recovery()
        return value

    def recover(update, first: int, last: int):  # type: ignore[no-untyped-def]
        return tuple(bar_update(item, binance_bar_type) for item in range(first, last + 1))

    inline = coordinator()
    inline_result = inline.accept(bar_update(103, binance_bar_type), recover)

    buffered = coordinator()
    buffered.begin_recovery()
    buffered.accept(bar_update(103, binance_bar_type), recover)
    buffered_result = buffered.complete_recovery(recover)

    assert tuple(item.update_id for item in inline_result) == tuple(item.update_id for item in buffered_result)
    assert inline.state == buffered.state
    assert inline.buffered_count == buffered.buffered_count == 0


def test_recovery_fact_and_waiting_websocket_duplicate_commit_once(binance_bar_type) -> None:  # type: ignore[no-untyped-def]
    coordinator = OnlyBinanceSpotContinuityCoordinator(10)
    coordinator.connected()
    coordinator.subscription_established()
    coordinator.begin_recovery()
    coordinator.accept_baseline(bar_update(100, binance_bar_type))
    coordinator.complete_recovery()
    recovery_entered = threading.Event()
    release_recovery = threading.Event()
    recovery_result: list[OnlyMarketDataInboundUpdate] = []
    websocket_result: list[OnlyMarketDataInboundUpdate] = []

    def recover(update, first: int, last: int):  # type: ignore[no-untyped-def]
        recovery_entered.set()
        assert release_recovery.wait(timeout=2)
        return tuple(bar_update(item, binance_bar_type) for item in range(first, last + 1))

    recovery = threading.Thread(
        target=lambda: recovery_result.extend(coordinator.accept(bar_update(103, binance_bar_type), recover))
    )
    recovery.start()
    assert recovery_entered.wait(timeout=2)
    websocket = threading.Thread(
        target=lambda: websocket_result.extend(coordinator.accept(bar_update(102, binance_bar_type), recover))
    )
    websocket.start()
    release_recovery.set()
    recovery.join(timeout=2)
    websocket.join(timeout=2)

    assert tuple(int(item.source_sequence) for item in recovery_result) == (101, 102, 103)
    assert websocket_result == []
    assert coordinator.state.value == "READY"
    assert coordinator.buffered_count == 0
