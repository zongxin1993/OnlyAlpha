from dataclasses import replace

from onlyalpha.data.enums import OnlyDataSequenceSemantics, OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataSequence, OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.data.identity import only_bar_update_id, only_trade_update_id
from onlyalpha.data.models import OnlyBarUpdate, OnlyMarketDataInboundUpdate, OnlyTradeTickUpdate
from onlyalpha.data.processor import OnlyMarketDataDeduplicator, OnlyMarketDataSequenceTracker
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.time import OnlyTimestamp

from ..domain_conformance.support.market_data import build_bar, build_trade_tick
from ..integration_demo.environment import OnlyIntegrationEnvironment


def _update(instrument_id: OnlyInstrumentId, sequence: int) -> OnlyMarketDataInboundUpdate:
    original = build_bar()
    bar_type = replace(original.bar_type, instrument_id=instrument_id)
    bar = replace(original, bar_type=bar_type)
    source = OnlyMarketDataSourceId("provider")
    version = OnlyDataVersion("normalizer-v1")
    timestamp = OnlyTimestamp.from_datetime(bar.ts_event)
    return OnlyMarketDataInboundUpdate(
        only_bar_update_id(source, instrument_id, bar_type, bar.bar_start, version),
        OnlyIntegrationEnvironment().runtime.config.runtime_id,  # type: ignore[arg-type]
        source,
        OnlyDataSequence(sequence),
        version,
        instrument_id,
        OnlyMarketDataType.BAR,
        OnlyBarUpdate(bar),
        timestamp,
        timestamp,
        sequence_semantics=OnlyDataSequenceSemantics.CONTIGUOUS,
    )


def test_fact_identity_is_transport_order_independent_and_envelope_v1_remains_readable() -> None:
    instrument = OnlyInstrumentId.parse("BTCUSDT.BINANCE")
    first = _update(instrument, 10)
    observed_again = replace(first, source_sequence=OnlyDataSequence(999))

    dedup = OnlyMarketDataDeduplicator()
    dedup.remember(first)
    assert dedup.contains(observed_again)

    legacy = first.to_dict()
    legacy["schema_version"] = 1
    legacy.pop("sequence_scope")
    legacy.pop("sequence_semantics")
    restored = OnlyMarketDataInboundUpdate.from_dict(legacy)
    assert restored.update_id == first.update_id
    assert restored.sequence_scope == first.sequence_scope


def test_contiguous_sequence_is_isolated_by_instrument_and_bar_type() -> None:
    btc = OnlyInstrumentId.parse("BTCUSDT.BINANCE")
    eth = OnlyInstrumentId.parse("ETHUSDT.BINANCE")
    tracker = OnlyMarketDataSequenceTracker()
    btc_100 = _update(btc, 100)
    eth_900 = _update(eth, 900)
    tracker.commit(btc_100)
    tracker.commit(eth_900)

    assert tracker.assess(_update(btc, 101)).gap is False
    assert tracker.assess(_update(eth, 901)).stale is False


def test_monotonic_sequence_does_not_invent_contiguous_gap() -> None:
    instrument = OnlyInstrumentId.parse("BTCUSDT.BINANCE")
    tracker = OnlyMarketDataSequenceTracker()
    first = replace(_update(instrument, 10), sequence_semantics=OnlyDataSequenceSemantics.MONOTONIC)
    later = replace(_update(instrument, 100), sequence_semantics=OnlyDataSequenceSemantics.MONOTONIC)
    tracker.commit(first)
    assert tracker.assess(later).gap is False
    assert tracker.assess(first).stale is True


def test_legacy_sequence_checkpoint_remains_readable_and_migrates_on_commit() -> None:
    instrument = OnlyInstrumentId.parse("BTCUSDT.BINANCE")
    tracker = OnlyMarketDataSequenceTracker()
    tracker.restore_checkpoint([{"source_id": "provider", "data_type": "BAR", "sequence": 100}])
    next_update = _update(instrument, 101)
    assert not tracker.assess(next_update).gap
    tracker.commit(next_update)
    captured = tracker.capture_checkpoint()
    assert isinstance(captured, list)
    assert captured[0]["scope"]["instrument_id"] == instrument.to_json()


def test_contiguous_trade_sequences_are_isolated_by_instrument() -> None:
    tracker = OnlyMarketDataSequenceTracker()
    source = OnlyMarketDataSourceId("provider")
    version = OnlyDataVersion("normalizer-v1")

    def update(instrument_id: OnlyInstrumentId, sequence: int) -> OnlyMarketDataInboundUpdate:
        trade = replace(build_trade_tick(), instrument_id=instrument_id, sequence=sequence)
        timestamp = OnlyTimestamp.from_datetime(trade.ts_event)
        return OnlyMarketDataInboundUpdate(
            only_trade_update_id(source, instrument_id, trade.trade_id, version),
            OnlyIntegrationEnvironment().runtime.config.runtime_id,  # type: ignore[arg-type]
            source,
            OnlyDataSequence(sequence),
            version,
            instrument_id,
            OnlyMarketDataType.TRADE,
            OnlyTradeTickUpdate(trade),
            timestamp,
            timestamp,
            sequence_semantics=OnlyDataSequenceSemantics.CONTIGUOUS,
        )

    btc = OnlyInstrumentId.parse("BTCUSDT.BINANCE")
    eth = OnlyInstrumentId.parse("ETHUSDT.BINANCE")
    tracker.commit(update(btc, 100))
    tracker.commit(update(eth, 900))
    assert not tracker.assess(update(btc, 101)).gap
    assert not tracker.assess(update(eth, 901)).stale
