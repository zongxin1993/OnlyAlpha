from dataclasses import replace

import pytest
from onlyalpha_plugin_binance.errors import OnlyBinanceError
from onlyalpha_plugin_binance.spot.data_source.continuity import OnlyBinanceSpotContinuityCoordinator
from onlyalpha_plugin_binance.spot.data_source.normalize import only_normalize_rest_kline, only_normalize_rest_trade
from test_data_source import _bar_type

from onlyalpha.data.enums import OnlyDataSequenceSemantics, OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataSequence, OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.data.identity import only_bar_update_id, only_trade_update_id
from onlyalpha.data.models import OnlyBarUpdate, OnlyMarketDataInboundUpdate, OnlyTradeTickUpdate
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp


def bar_update(sequence: int) -> OnlyMarketDataInboundUpdate:
    instrument, bar_type = _bar_type()
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


def trade_update(sequence: int) -> OnlyMarketDataInboundUpdate:
    instrument, _ = _bar_type()
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


def test_exact_gap_recovery_publishes_stable_order_and_returns_ready() -> None:
    coordinator = OnlyBinanceSpotContinuityCoordinator(10)
    coordinator.connected()
    coordinator.begin_recovery()
    coordinator.accept_baseline(bar_update(100))
    assert coordinator.ready() == ()

    incoming = bar_update(103)

    def recover(update, first: int, last: int):  # type: ignore[no-untyped-def]
        assert update == incoming
        assert (first, last) == (101, 102)
        return tuple(bar_update(item) for item in range(first, last + 1))

    accepted = coordinator.accept(incoming, recover)
    assert tuple(int(item.source_sequence) for item in accepted) == (101, 102, 103)
    assert coordinator.state.value == "READY"


def test_unproven_recovery_remains_not_ready_and_buffer_overflow_fails_closed() -> None:
    coordinator = OnlyBinanceSpotContinuityCoordinator(1)
    coordinator.connected()
    coordinator.begin_recovery()
    coordinator.accept_baseline(bar_update(100))
    coordinator.ready()

    assert coordinator.accept(bar_update(103)) == ()
    assert coordinator.state.value == "RECOVERING"
    with pytest.raises(OnlyBinanceError, match="RECOVERY_BUFFER_OVERFLOW"):
        coordinator.buffer(replace(bar_update(104), source_sequence=OnlyDataSequence(104)))
    assert coordinator.state.value == "FAILED"


def test_trade_gap_recovery_duplicate_and_out_of_order_converge() -> None:
    coordinator = OnlyBinanceSpotContinuityCoordinator(10)
    coordinator.connected()
    coordinator.begin_recovery()
    coordinator.accept_baseline(trade_update(100))
    coordinator.ready()

    incoming = trade_update(103)
    accepted = coordinator.accept(
        incoming,
        lambda update, first, last: tuple(trade_update(item) for item in range(first, last + 1)),
    )
    assert tuple(int(item.source_sequence) for item in accepted) == (101, 102, 103)
    assert coordinator.accept(incoming) == ()
    assert coordinator.accept(trade_update(99)) == ()
    assert coordinator.state.value == "READY"
