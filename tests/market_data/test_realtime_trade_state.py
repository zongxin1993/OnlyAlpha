from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from onlyalpha.data.enums import OnlyDataSequenceSemantics, OnlyMarketDataProcessingStatus, OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataSequence, OnlyDataVersion
from onlyalpha.data.identity import only_trade_update_id
from onlyalpha.data.models import OnlyMarketDataInboundUpdate, OnlyTradeTickUpdate
from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.identifiers import OnlyTradeId
from onlyalpha.domain.market import OnlyTradeTick
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from tests.integration_demo.environment import DAY_ONE, INSTRUMENT_ID, OnlyIntegrationEnvironment


def _trade(env: OnlyIntegrationEnvironment, sequence: int, price: str) -> OnlyMarketDataInboundUpdate:
    timestamp = datetime(2026, 1, 5, 1, 30, tzinfo=UTC)
    source_id = env.market_data_gateway.source_id
    version = OnlyDataVersion("trade-v1")
    trade = OnlyTradeTick(
        INSTRUMENT_ID,
        timestamp,
        timestamp,
        sequence,
        str(source_id),
        OnlyPrice(Decimal(price), 2),
        OnlyQuantity(Decimal("1"), 0),
        OnlyOrderSide.BUY,
        OnlyTradeId(f"trade-{sequence}"),
    )
    observed = OnlyTimestamp.from_datetime(timestamp)
    return OnlyMarketDataInboundUpdate(
        only_trade_update_id(source_id, INSTRUMENT_ID, trade.trade_id, version),
        env.runtime.config.runtime_id,  # type: ignore[arg-type]
        source_id,
        OnlyDataSequence(sequence),
        version,
        INSTRUMENT_ID,
        OnlyMarketDataType.TRADE,
        OnlyTradeTickUpdate(trade),
        observed,
        observed,
        sequence_semantics=OnlyDataSequenceSemantics.CONTIGUOUS,
    )


def test_trade_projection_applies_without_strategy_dispatch_and_snapshot_is_isolated() -> None:
    env = OnlyIntegrationEnvironment()
    first = env.market_data_processor.process(_trade(env, 100, "10.00"))

    assert first.status is OnlyMarketDataProcessingStatus.APPLIED
    assert first.pipeline_result is None
    assert first.dispatches == ()
    snapshot = env.runtime.realtime_market_state.capture(
        OnlyTimestamp.from_unix_nanos(env.runtime.clock.timestamp_ns())
    )
    assert snapshot.latest_trade(INSTRUMENT_ID).trade.price.value == Decimal("10.00")  # type: ignore[union-attr]

    env.market_data_processor.process(_trade(env, 101, "10.01"))
    assert snapshot.latest_trade(INSTRUMENT_ID).trade.price.value == Decimal("10.00")  # type: ignore[union-attr]
    current = env.runtime.realtime_market_state.capture(OnlyTimestamp.from_unix_nanos(env.runtime.clock.timestamp_ns()))
    assert current.latest_trade(INSTRUMENT_ID).trade.price.value == Decimal("10.01")  # type: ignore[union-attr]
    assert current.fingerprint != snapshot.fingerprint


def test_duplicate_stale_and_gap_never_mutate_trusted_trade_state() -> None:
    env = OnlyIntegrationEnvironment()
    trade_100 = _trade(env, 100, "10.00")
    trade_101 = _trade(env, 101, "10.01")
    env.market_data_processor.process(trade_100)
    env.market_data_processor.process(trade_101)

    duplicate = env.market_data_processor.process(trade_101)
    stale = env.market_data_processor.process(
        replace(_trade(env, 99, "9.99"), update_id=_trade(env, 99, "9.99").update_id)
    )
    gap = env.market_data_processor.process(_trade(env, 105, "10.05"))
    snapshot = env.runtime.realtime_market_state.capture(
        OnlyTimestamp.from_unix_nanos(env.runtime.clock.timestamp_ns())
    )

    assert duplicate.status is OnlyMarketDataProcessingStatus.DUPLICATE
    assert stale.status is OnlyMarketDataProcessingStatus.STALE
    assert gap.status is OnlyMarketDataProcessingStatus.GAP_DETECTED
    reference = snapshot.latest_trade(INSTRUMENT_ID)
    assert reference is not None and reference.source_sequence == 101
    assert snapshot.has_unresolved_gap(reference)


def test_gap_recovery_advances_only_in_canonical_sequence() -> None:
    env = OnlyIntegrationEnvironment()
    for sequence in (100, 101):
        env.market_data_processor.process(_trade(env, sequence, f"{sequence / 10:.2f}"))
    env.market_data_processor.process(_trade(env, 105, "10.50"))

    for sequence in (102, 103, 104, 105):
        result = env.market_data_processor.process(_trade(env, sequence, f"{sequence / 10:.2f}"))
        assert result.status is OnlyMarketDataProcessingStatus.APPLIED
        if sequence < 105:
            intermediate = env.runtime.realtime_market_state.capture(
                OnlyTimestamp.from_unix_nanos(env.runtime.clock.timestamp_ns())
            )
            reference = intermediate.latest_trade(INSTRUMENT_ID)
            assert reference is not None and intermediate.has_unresolved_gap(reference)

    snapshot = env.runtime.realtime_market_state.capture(
        OnlyTimestamp.from_unix_nanos(env.runtime.clock.timestamp_ns())
    )
    reference = snapshot.latest_trade(INSTRUMENT_ID)
    assert reference is not None and reference.source_sequence == 105
    assert not snapshot.has_unresolved_gap(reference)


def test_interleaved_trades_do_not_change_bar_strategy_dispatch() -> None:
    bars_only = OnlyIntegrationEnvironment()
    with_trades = OnlyIntegrationEnvironment()
    bars_only.start()
    with_trades.start()
    for minute in range(3):
        bars_only.process_bar(DAY_ONE, minute, "10.00")
        with_trades.market_data_processor.process(_trade(with_trades, 100 + minute, f"10.0{minute}"))
        with_trades.process_bar(DAY_ONE, minute, "10.00")

    assert len(bars_only.cluster.snapshots) == len(with_trades.cluster.snapshots)
    assert tuple(bars_only.cluster.snapshots) == tuple(with_trades.cluster.snapshots)
    assert bars_only.cluster.submit_results == with_trades.cluster.submit_results
