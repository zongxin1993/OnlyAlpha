from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from onlyalpha.data.enums import OnlyDataSequenceSemantics, OnlyMarketDataQualityFlag, OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataSequence, OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.data.identity import only_trade_update_id
from onlyalpha.data.models import OnlyMarketDataInboundUpdate, OnlyMarketDataQuality, OnlyTradeTickUpdate
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderType
from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyOrderRequestId, OnlyRuntimeId, OnlyTradeId
from onlyalpha.domain.market import OnlyTradeTick
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.execution.reference import (
    OnlyExecutionReferenceFallback,
    OnlyExecutionReferenceKind,
    OnlyExecutionReferencePlanningService,
    OnlyExecutionReferenceProfile,
)
from onlyalpha.market_data.realtime_state import OnlyRealtimeMarketStateStore
from onlyalpha.risk.enums import OnlyOrderRiskChange
from onlyalpha.strategy.execution import OnlyStrategyDecision, OnlyStrategyObservationKey
from tests.integration_demo.environment import DAY_ONE, OnlyIntegrationEnvironment
from tests.integration_demo.environment import INSTRUMENT_ID as INTEGRATION_INSTRUMENT

NOW = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, tzinfo=UTC))
RUNTIME = OnlyRuntimeId("runtime")
SOURCE = OnlyMarketDataSourceId("source")
INSTRUMENT = OnlyInstrumentId.parse("BTCUSDT.BINANCE")
VERSION = OnlyDataVersion("v1")


def _profile(**changes) -> OnlyExecutionReferenceProfile:
    values = dict(
        profile_id="last-trade-v1",
        policy_version=1,
        reference_kind=OnlyExecutionReferenceKind.LAST_TRADE,
        fallback=OnlyExecutionReferenceFallback.NONE,
        max_age_ns=10_000_000_000,
        required_source_id=str(SOURCE),
        maximum_deviation_rate=Decimal("0.05"),
    )
    values.update(changes)
    return OnlyExecutionReferenceProfile(**values)


def _request(price: str = "101.00") -> OnlyOrderRequest:
    return OnlyOrderRequest(
        OnlyOrderRequestId("request"),
        INSTRUMENT,
        OnlyOrderSide.BUY,
        OnlyOrderType.LIMIT,
        OnlyQuantity(Decimal("1"), 0),
        offset=OnlyOffset.OPEN,
        price=OnlyPrice(Decimal(price), 2),
    )


def _update(sequence: int = 1, price: str = "100.00") -> OnlyMarketDataInboundUpdate:
    trade = OnlyTradeTick(
        INSTRUMENT,
        NOW.to_datetime(),
        NOW.to_datetime(),
        sequence,
        str(SOURCE),
        OnlyPrice(Decimal(price), 2),
        OnlyQuantity(Decimal("1"), 0),
        OnlyOrderSide.BUY,
        OnlyTradeId(f"trade-{sequence}"),
    )
    return OnlyMarketDataInboundUpdate(
        only_trade_update_id(SOURCE, INSTRUMENT, trade.trade_id, VERSION),
        RUNTIME,
        SOURCE,
        OnlyDataSequence(sequence),
        VERSION,
        INSTRUMENT,
        OnlyMarketDataType.TRADE,
        OnlyTradeTickUpdate(trade),
        NOW,
        NOW,
        sequence_semantics=OnlyDataSequenceSemantics.CONTIGUOUS,
    )


def test_risk_increasing_plan_uses_one_snapshot_and_exact_trade_evidence() -> None:
    state = OnlyRealtimeMarketStateStore(RUNTIME)
    state.apply_trade(_update(), OnlyMarketDataQuality(), 1)
    planner = OnlyExecutionReferencePlanningService(state, _profile())

    result = planner.plan(_request(), OnlyOrderRiskChange.RISK_INCREASING, NOW)

    assert result.accepted and result.evidence is not None
    assert result.evidence.market_update_id == str(_update().update_id)
    assert result.evidence.snapshot_fingerprint == result.snapshot.fingerprint
    assert result.evidence.profile_fingerprint == planner.profile.fingerprint
    assert result.evidence.reference_price.value == Decimal("100.00")
    assert result.evidence.resolved_order_price.value == Decimal("101.00")


def test_missing_stale_gap_source_and_price_deviation_fail_closed() -> None:
    empty = OnlyRealtimeMarketStateStore(RUNTIME)
    assert (
        OnlyExecutionReferencePlanningService(empty, _profile())
        .plan(_request(), OnlyOrderRiskChange.RISK_INCREASING, NOW)
        .failure_code
        == "REFERENCE_UNAVAILABLE"
    )

    state = OnlyRealtimeMarketStateStore(RUNTIME)
    update = _update()
    state.apply_trade(update, OnlyMarketDataQuality(), 1)
    stale_at = OnlyTimestamp.from_unix_nanos(NOW.unix_nanos + 11_000_000_000)
    assert (
        OnlyExecutionReferencePlanningService(state, _profile())
        .plan(_request(), OnlyOrderRiskChange.RISK_INCREASING, stale_at)
        .failure_code
        == "REFERENCE_STALE"
    )

    delayed = OnlyRealtimeMarketStateStore(RUNTIME)
    delayed.apply_trade(replace(update, ts_init=stale_at), OnlyMarketDataQuality(), 1)
    assert (
        OnlyExecutionReferencePlanningService(delayed, _profile())
        .plan(_request(), OnlyOrderRiskChange.RISK_INCREASING, stale_at)
        .failure_code
        == "REFERENCE_STALE"
    )

    state.mark_gap(update.sequence_scope, 2)  # type: ignore[arg-type]
    assert (
        OnlyExecutionReferencePlanningService(state, _profile())
        .plan(_request(), OnlyOrderRiskChange.RISK_INCREASING, NOW)
        .failure_code
        == "REFERENCE_GAP_UNRESOLVED"
    )

    assert (
        OnlyExecutionReferencePlanningService(state, _profile(required_source_id="other"))
        .plan(_request(), OnlyOrderRiskChange.RISK_INCREASING, NOW)
        .failure_code
        == "REFERENCE_SOURCE_MISMATCH"
    )

    fresh = OnlyRealtimeMarketStateStore(RUNTIME)
    fresh.apply_trade(update, OnlyMarketDataQuality(), 1)
    assert (
        OnlyExecutionReferencePlanningService(fresh, _profile())
        .plan(_request("106.00"), OnlyOrderRiskChange.RISK_INCREASING, NOW)
        .failure_code
        == "ORDER_PRICE_DEVIATION_EXCEEDED"
    )


def test_risk_reducing_path_does_not_require_reference() -> None:
    result = OnlyExecutionReferencePlanningService(OnlyRealtimeMarketStateStore(RUNTIME), _profile()).plan(
        _request(), OnlyOrderRiskChange.RISK_REDUCING, NOW
    )
    assert result.accepted and result.evidence is None


def test_invalid_quality_reference_is_denied_even_if_snapshot_boundary_is_corrupted() -> None:
    state = OnlyRealtimeMarketStateStore(RUNTIME)
    state.apply_trade(_update(), OnlyMarketDataQuality(), 1)
    valid = state.capture(NOW)
    reference = valid.latest_trade(INSTRUMENT)
    assert reference is not None
    invalid_reference = replace(
        reference,
        quality=OnlyMarketDataQuality(frozenset({OnlyMarketDataQualityFlag.SOURCE_CONFLICT})),
    )
    invalid = replace(valid, trades=(invalid_reference,))

    class CorruptedSnapshotSource:
        @staticmethod
        def capture(captured_at):
            del captured_at
            return invalid

    result = OnlyExecutionReferencePlanningService(CorruptedSnapshotSource(), _profile()).plan(  # type: ignore[arg-type]
        _request(), OnlyOrderRiskChange.RISK_INCREASING, NOW
    )

    assert result.failure_code == "REFERENCE_QUALITY_INVALID"


def test_restart_starts_reference_projection_empty_despite_prior_runtime_state() -> None:
    before_restart = OnlyRealtimeMarketStateStore(RUNTIME)
    before_restart.apply_trade(_update(), OnlyMarketDataQuality(), 1)
    assert before_restart.capture(NOW).latest_trade(INSTRUMENT) is not None

    after_restart = OnlyRealtimeMarketStateStore(RUNTIME)
    result = OnlyExecutionReferencePlanningService(after_restart, _profile()).plan(
        _request(), OnlyOrderRiskChange.RISK_INCREASING, NOW
    )

    assert result.failure_code == "REFERENCE_UNAVAILABLE"


def test_reference_denial_does_not_mutate_original_strategy_decision() -> None:
    decision = OnlyStrategyDecision(
        "a" * 64,
        str(INSTRUMENT),
        OnlyStrategyObservationKey(str(INSTRUMENT), 1, "TIME", "LAST", "EXTERNAL", "RAW", NOW.unix_nanos),
        "b" * 64,
        NOW,
        True,
        True,
        False,
    )

    denied = OnlyExecutionReferencePlanningService(OnlyRealtimeMarketStateStore(RUNTIME), _profile()).plan(
        _request(), OnlyOrderRiskChange.RISK_INCREASING, NOW
    )

    assert denied.failure_code == "REFERENCE_UNAVAILABLE"
    assert decision.entry and not decision.exit
    assert decision.strategy_fingerprint == "a" * 64


def test_order_intent_persists_exact_trade_reference_causal_chain() -> None:
    profile = _profile(
        required_source_id="integration-runtime-in-memory-live",
        max_age_ns=600_000_000_000,
        maximum_deviation_rate=None,
    )
    environment = OnlyIntegrationEnvironment(execution_reference_profile=profile)
    environment.start()
    for minute in range(3):
        environment.process_bar(DAY_ONE, minute, "10.00")
    trade = _update()
    observed = OnlyTimestamp.from_unix_nanos(environment.runtime.clock.timestamp_ns())
    canonical_trade = replace(
        trade.payload.trade,  # type: ignore[union-attr]
        instrument_id=INTEGRATION_INSTRUMENT,
        ts_event=observed.to_datetime(),
        ts_init=observed.to_datetime(),
        source=str(environment.market_data_gateway.source_id),
    )
    trade = replace(
        trade,
        runtime_id=environment.runtime.config.runtime_id,  # type: ignore[arg-type]
        source_id=environment.market_data_gateway.source_id,
        instrument_id=INTEGRATION_INSTRUMENT,
        update_id=only_trade_update_id(
            environment.market_data_gateway.source_id,
            INTEGRATION_INSTRUMENT,
            canonical_trade.trade_id,
            trade.data_version,
        ),
        payload=replace(trade.payload, trade=canonical_trade),  # type: ignore[union-attr]
        ts_event=observed,
        ts_init=observed,
        sequence_scope=None,
    )
    environment.market_data_processor.process(trade)

    submitted = environment.submit_buy()
    intent = environment.runtime.execution_transaction_query.transactions_for_order(
        environment.runtime.config.runtime_id,  # type: ignore[arg-type]
        submitted.order_id,
    )[0].fact

    assert intent.execution_reference is not None
    assert intent.execution_reference.market_update_id == str(trade.update_id)
    assert intent.execution_reference.reference_price.value == Decimal("100.00")
    assert intent.execution_reference.profile_fingerprint == profile.fingerprint
