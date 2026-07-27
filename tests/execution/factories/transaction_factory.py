"""Independent, deterministic prepared execution transaction fixtures."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

from onlyalpha.broker import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.domain.enums import (
    OnlyCurrencyType,
    OnlyLiquiditySide,
    OnlyOffset,
    OnlyOrderSide,
    OnlyOrderStatus,
    OnlyOrderType,
)
from onlyalpha.domain.execution import OnlyOrderFill
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyEngineId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyRuntimeId,
    OnlySymbol,
    OnlyTradeId,
    OnlyVenueId,
)
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyMultiplier, OnlyPrice, OnlyQuantity
from onlyalpha.event.model import OnlyEvent, OnlyEventSource, OnlyEventType
from onlyalpha.execution import (
    OnlyAccountExecutionProjection,
    OnlyAllocationExecutionProjection,
    OnlyCashReservationExecutionProjection,
    OnlyCommittedExecutionFactDraft,
    OnlyExecutionPrecondition,
    OnlyExecutionProjection,
    OnlyExecutionProjectionComponent,
    OnlyExecutionProjectionIdentity,
    OnlyExecutionTransactionEventFactory,
    OnlyFeeExecutionProjection,
    OnlyFeeInstructionReplay,
    OnlyFeeRecordReplay,
    OnlyMarginExecutionProjection,
    OnlyMarginReservationExecutionProjection,
    OnlyOrderExecutionProjection,
    OnlyPositionExecutionProjection,
    OnlyPositionReservationExecutionProjection,
    OnlyPreparedExecutionTransaction,
    OnlyReservationStatus,
    OnlyRiskExecutionProjection,
    OnlyRiskReservationExecutionProjection,
    OnlySettlementExecutionProjection,
    OnlySettlementProjectionState,
    OnlySettlementRecordReplay,
    OnlyStrategyLedgerExecutionProjection,
    OnlyValuationExecutionProjection,
    only_execution_transaction_id,
    only_with_execution_projection_hash,
)
from onlyalpha.fee import (
    OnlyBrokerFeeReportingMode,
    OnlyFeeAuthority,
    OnlyFeeBreakdown,
    OnlyFeeComponent,
    OnlyFeeStatus,
    OnlyFeeType,
)
from onlyalpha.market.models import OnlyPositionEffect
from onlyalpha.position.enums import OnlyPositionMode, OnlyPositionSide
from onlyalpha.risk.enums import OnlyRiskLevel, OnlyRiskReservationState
from onlyalpha.strategy.identifiers import OnlyStrategyId

_TEST_RUNTIME_ID = OnlyRuntimeId("runtime")
_TEST_TRADE_ID = OnlyTradeId("trade")
_TEST_UPDATE_ID = OnlyBrokerUpdateId("update")


def only_test_execution_fact_draft(
    *,
    runtime_id: OnlyRuntimeId = _TEST_RUNTIME_ID,
    trade_id: OnlyTradeId = _TEST_TRADE_ID,
    update_id: OnlyBrokerUpdateId = _TEST_UPDATE_ID,
) -> OnlyCommittedExecutionFactDraft:
    timestamp = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, tzinfo=UTC))
    currency = OnlyCurrency("CNY", 2, OnlyCurrencyType.FIAT)
    zero = OnlyMoney(Decimal("0.00"), currency)
    return OnlyCommittedExecutionFactDraft(
        execution_id=f"EXEC-{runtime_id}-{trade_id}",
        trade_id=trade_id,
        venue_trade_id="venue-trade",
        order_id=OnlyOrderId("order"),
        client_order_id="client-order",
        request_id="request",
        broker_update_id=update_id,
        runtime_id=runtime_id,
        gateway_id=OnlyBrokerGatewayId("gateway"),
        account_id=OnlyAccountId("account"),
        cluster_id=OnlyClusterId("cluster"),
        strategy_id=OnlyStrategyId("strategy"),
        instrument_id=OnlyInstrumentId(OnlySymbol("600000"), OnlyVenueId("XSHG")),
        venue_id="XSHG",
        source_sequence=7,
        processing_sequence=3,
        correlation_id="correlation",
        causation_id="causation",
        external_event_id="external",
        ts_event=timestamp,
        ts_init=timestamp,
        trading_day=OnlyTradingDay(date(2026, 1, 1)),
        order_side=OnlyOrderSide.BUY,
        order_type=OnlyOrderType.LIMIT,
        offset=OnlyOffset.OPEN,
        position_side=OnlyPositionSide.LONG,
        position_effect=OnlyPositionEffect.OPEN,
        position_mode=OnlyPositionMode.NETTING,
        liquidity_side=OnlyLiquiditySide.TAKER,
        fill_quantity=OnlyQuantity(Decimal("2"), 0),
        fill_price=OnlyPrice(Decimal("10.00"), 2),
        cumulative_filled_quantity=OnlyQuantity(Decimal("2"), 0),
        remaining_quantity=OnlyQuantity(Decimal("0"), 0),
        order_status_after=OnlyOrderStatus.FILLED,
        currency=currency,
        contract_multiplier=OnlyMultiplier(Decimal("1"), 0),
        gross_notional=OnlyMoney(Decimal("20.00"), currency),
        settled_notional=OnlyMoney(Decimal("20.00"), currency),
        authoritative_fee_total=zero,
        market_fee=zero,
        broker_fee=zero,
        tax=zero,
        commission=zero,
        other_fee=zero,
        reported_broker_fee=None,
        fee_reporting_mode=OnlyBrokerFeeReportingMode.NONE,
        reference_price=OnlyPrice(Decimal("10.00"), 2),
        slippage=zero,
        realized_pnl_delta=zero,
        cash_delta=OnlyMoney(Decimal("-20.00"), currency),
        fee_instruction_id="fee-instruction",
        fee_authority="NONE",
        fee_status=OnlyFeeStatus.CONFIRMED.value,
        market_fee_schedule_ids=(),
        market_fee_schedule_versions=(),
        broker_fee_schedule_ids=(),
        broker_fee_schedule_versions=(),
        fee_breakdown=OnlyFeeBreakdown.empty(currency, OnlyFeeStatus.CONFIRMED),
        market_profile_id="GENERIC_T0_CASH",
        market_profile_version="1",
        compiled_rule_fingerprint="compiled",
        reference_fingerprint="reference",
        trade_instruction_id="trade-instruction",
        settlement_instruction_id="settlement",
        settlement_status="SETTLED",
        asset_available_on=OnlyTradingDay(date(2026, 1, 1)),
        cash_available_on=OnlyTradingDay(date(2026, 1, 1)),
        legal_settlement_date=OnlyTradingDay(date(2026, 1, 1)),
        margin_instruction_id=None,
        margin_action=None,
        margin_currency=None,
        margin_amount=None,
        reserved_margin_delta=None,
        occupied_margin_delta=None,
        released_margin_delta=None,
        maintenance_margin_after=None,
        position_quantity_delta=Decimal("2"),
        position_realized_pnl_delta=zero,
        allocation_quantity_delta=Decimal("2"),
        account_cash_delta=OnlyMoney(Decimal("-20.00"), currency),
        account_fee_delta=zero,
        account_realized_pnl_delta=zero,
        ledger_cash_delta=OnlyMoney(Decimal("-20.00"), currency),
        ledger_fee_delta=zero,
        ledger_realized_pnl_delta=zero,
    )


def only_test_execution_projections() -> tuple[OnlyExecutionProjection, ...]:
    day = OnlyTradingDay(date(2026, 1, 1))
    timestamp = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, tzinfo=UTC))
    currency = OnlyCurrency("CNY", 2, OnlyCurrencyType.FIAT)
    zero = OnlyMoney(Decimal("0.00"), currency)
    one = OnlyMoney(Decimal("1.00"), currency)
    two = OnlyMoney(Decimal("2.00"), currency)
    quantity_zero = OnlyQuantity(Decimal("0"), 0)
    quantity_one = OnlyQuantity(Decimal("1"), 0)
    quantity_two = OnlyQuantity(Decimal("2"), 0)
    instrument_id = OnlyInstrumentId(OnlySymbol("600000"), OnlyVenueId("XSHG"))
    order_id = OnlyOrderId("order")

    def identity(
        component: OnlyExecutionProjectionComponent, sequence: int, key: str
    ) -> OnlyExecutionProjectionIdentity:
        return OnlyExecutionProjectionIdentity(component, key, 0, 1, sequence, "0" * 64)

    state = OnlySettlementProjectionState(
        "settlement",
        "account",
        "600000.XSHG",
        "order",
        "trade",
        Decimal("2"),
        Decimal("20"),
        True,
        True,
        True,
        True,
        day,
        day,
        day,
        day,
    )
    record = OnlySettlementRecordReplay(
        "settlement",
        "account",
        "600000.XSHG",
        "order",
        "trade",
        day,
        Decimal("2"),
        Decimal("20"),
        Decimal("20"),
        True,
        1,
    )
    fee_component = OnlyFeeComponent(
        OnlyFeeType.BROKER_COMMISSION, OnlyFeeAuthority.BROKER, one, OnlyFeeStatus.CONFIRMED, "fee-source"
    )
    fee_breakdown = OnlyFeeBreakdown(currency, (fee_component,), one, OnlyFeeStatus.CONFIRMED)
    projections: tuple[OnlyExecutionProjection, ...] = (
        OnlyOrderExecutionProjection(
            identity(OnlyExecutionProjectionComponent.ORDER, 1, "order"),
            order_id,
            OnlyOrderStatus.PARTIALLY_FILLED,
            OnlyOrderStatus.FILLED,
            quantity_one,
            quantity_two,
            OnlyPrice(Decimal("10.00"), 2),
            OnlyPrice(Decimal("10.00"), 2),
            OnlyOrderFill(
                OnlyTradeId("trade"), order_id, OnlyPrice(Decimal("10.00"), 2), quantity_one, timestamp, timestamp
            ),
            "update",
        ),
        OnlyPositionExecutionProjection(
            identity(OnlyExecutionProjectionComponent.POSITION, 2, "position"),
            "position",
            quantity_zero,
            quantity_two,
            quantity_zero,
            quantity_two,
            None,
            OnlyPrice(Decimal("10.00"), 2),
            zero,
            zero,
        ),
        OnlyAllocationExecutionProjection(
            identity(OnlyExecutionProjectionComponent.ALLOCATION, 3, "allocation"),
            "allocation",
            quantity_zero,
            quantity_two,
            zero,
            OnlyMoney(Decimal("20.00"), currency),
            zero,
        ),
        OnlySettlementExecutionProjection(
            identity(OnlyExecutionProjectionComponent.SETTLEMENT, 4, "settlement"), None, state, (record,)
        ),
        OnlyMarginExecutionProjection(
            identity(OnlyExecutionProjectionComponent.MARGIN, 5, "margin"), "margin", two, one, zero, one, zero, one
        ),
        OnlyFeeExecutionProjection(
            identity(OnlyExecutionProjectionComponent.FEE, 6, "fee"),
            OnlyFeeInstructionReplay(
                "fee-instruction", "runtime", "cluster", "account", "order", "trade", "resolver", "fee-key", timestamp
            ),
            (
                OnlyFeeRecordReplay(
                    "fee-record", "fee-instruction", "account", "order", "trade", one, "BROKER_COMMISSION"
                ),
            ),
            one,
            fee_breakdown,
        ),
        OnlyAccountExecutionProjection(
            identity(OnlyExecutionProjectionComponent.ACCOUNT, 7, "account"),
            OnlyAccountId("account"),
            OnlyMoney(Decimal("100"), currency),
            OnlyMoney(Decimal("79"), currency),
            zero,
            zero,
            zero,
            zero,
            zero,
            zero,
            zero,
            one,
            zero,
            OnlyMoney(Decimal("20"), currency),
            OnlyMoney(Decimal("100"), currency),
            OnlyMoney(Decimal("99"), currency),
        ),
        OnlyStrategyLedgerExecutionProjection(
            identity(OnlyExecutionProjectionComponent.STRATEGY_LEDGER, 8, "ledger"),
            "ledger",
            OnlyMoney(Decimal("100"), currency),
            OnlyMoney(Decimal("79"), currency),
            zero,
            zero,
            zero,
            zero,
            zero,
            one,
            OnlyMoney(Decimal("100"), currency),
            OnlyMoney(Decimal("99"), currency),
            0,
            1,
        ),
        OnlyCashReservationExecutionProjection(
            identity(OnlyExecutionProjectionComponent.ACCOUNT_CASH_RESERVATION, 9, "account-cash"),
            "account-cash",
            "account",
            currency,
            two,
            one,
            one,
            zero,
            OnlyReservationStatus.ACTIVE,
            OnlyReservationStatus.CONSUMED,
        ),
        OnlyCashReservationExecutionProjection(
            identity(OnlyExecutionProjectionComponent.STRATEGY_CASH_RESERVATION, 10, "strategy-cash"),
            "strategy-cash",
            "cluster",
            currency,
            two,
            one,
            zero,
            one,
            OnlyReservationStatus.ACTIVE,
            OnlyReservationStatus.PARTIALLY_CONSUMED,
        ),
        OnlyPositionReservationExecutionProjection(
            identity(OnlyExecutionProjectionComponent.POSITION_RESERVATION, 11, "position-reservation"),
            "position-reservation",
            order_id,
            instrument_id,
            quantity_two,
            quantity_one,
            quantity_zero,
            quantity_one,
            OnlyReservationStatus.ACTIVE,
            OnlyReservationStatus.PARTIALLY_CONSUMED,
        ),
        OnlyMarginReservationExecutionProjection(
            identity(OnlyExecutionProjectionComponent.MARGIN_RESERVATION, 12, "margin-reservation"),
            "margin-reservation",
            OnlyAccountId("account"),
            instrument_id,
            currency,
            two,
            one,
            zero,
            zero,
            one,
            zero,
            zero,
        ),
        OnlyRiskReservationExecutionProjection(
            identity(OnlyExecutionProjectionComponent.RISK_RESERVATION, 13, "risk-reservation"),
            "risk-reservation",
            OnlyClusterId("cluster"),
            OnlyAccountId("account"),
            instrument_id,
            order_id,
            quantity_two,
            quantity_one,
            two,
            one,
            quantity_one,
            one,
            OnlyRiskReservationState.ACTIVE,
            OnlyRiskReservationState.ACTIVE,
        ),
        OnlyRiskExecutionProjection(
            identity(OnlyExecutionProjectionComponent.RISK, 14, "risk"),
            OnlyClusterId("cluster"),
            OnlyAccountId("account"),
            instrument_id,
            order_id,
            quantity_two,
            quantity_one,
            two,
            one,
            OnlyRiskLevel.NORMAL,
            OnlyRiskLevel.NORMAL,
        ),
        OnlyValuationExecutionProjection(
            identity(OnlyExecutionProjectionComponent.VALUATION, 15, "valuation"),
            OnlyAccountId("account"),
            timestamp,
            zero,
            OnlyMoney(Decimal("20"), currency),
            zero,
            zero,
        ),
    )
    return tuple(only_with_execution_projection_hash(projection) for projection in projections)


def only_test_execution_preconditions(
    projections: tuple[OnlyExecutionProjection, ...],
) -> tuple[OnlyExecutionPrecondition, ...]:
    return tuple(
        OnlyExecutionPrecondition(item.identity.component, item.identity.entity_key, item.identity.expected_version)
        for item in projections
    )


def only_test_execution_events(*, transaction_id: str, runtime_id: OnlyRuntimeId) -> tuple[OnlyEvent, ...]:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    factory = OnlyExecutionTransactionEventFactory()
    return tuple(
        factory.create(
            transaction_id=transaction_id,
            event_sequence=index,
            event_type=OnlyEventType(f"TRADE_EVENT_{index}"),
            timestamp=timestamp,
            engine_id=OnlyEngineId("engine"),
            runtime_id=runtime_id,
            source=OnlyEventSource("execution"),
            payload={"sequence": index},
        )
        for index in (1, 2)
    )


def only_test_prepared_execution_transaction(
    *,
    prepared_at: OnlyTimestamp | None = None,
    runtime_id: OnlyRuntimeId = _TEST_RUNTIME_ID,
    trade_id: OnlyTradeId = _TEST_TRADE_ID,
    update_id: OnlyBrokerUpdateId = _TEST_UPDATE_ID,
) -> OnlyPreparedExecutionTransaction:
    fact = only_test_execution_fact_draft(runtime_id=runtime_id, trade_id=trade_id, update_id=update_id)
    transaction_id = only_execution_transaction_id(
        runtime_id=runtime_id,
        gateway_id=fact.gateway_id,
        account_id=fact.account_id,
        broker_update_id=update_id,
        trade_id=trade_id,
    )
    projections = only_test_execution_projections()
    return OnlyPreparedExecutionTransaction(
        transaction_id,
        runtime_id,
        fact.gateway_id,
        fact.account_id,
        update_id,
        trade_id,
        fact.source_sequence,
        fact.ts_init if prepared_at is None else prepared_at,
        fact,
        projections,
        only_test_execution_events(transaction_id=transaction_id, runtime_id=runtime_id),
        only_test_execution_preconditions(projections),
    )


def only_test_rehash(prepared: OnlyPreparedExecutionTransaction, **changes: object) -> OnlyPreparedExecutionTransaction:
    return replace(prepared, **changes, authority_hash="", payload_hash="")
