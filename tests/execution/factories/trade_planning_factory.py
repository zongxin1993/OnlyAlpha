"""Deterministic Generic T0 Cash Trade planning authority."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

from onlyalpha.broker import OnlyBrokerGatewayId, OnlyBrokerTradeUpdate, OnlyBrokerUpdateId
from onlyalpha.domain.enums import OnlyRuntimeMode
from onlyalpha.domain.identifiers import OnlyEngineId, OnlyPositionId
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.domain.value import OnlyMoney, OnlyMultiplier
from onlyalpha.execution import (
    OnlyAccountCashReservationExecutionProjection,
    OnlyAccountExecutionProjection,
    OnlyAllocationCreationAuthority,
    OnlyExecutionPositionScope,
    OnlyOrderExecutionProjection,
    OnlyPositionCreationAuthority,
    OnlyPositionScopeResolutionSource,
    OnlyPreparedExecutionTransaction,
    OnlyRiskExecutionProjection,
    OnlyRiskReservationExecutionProjection,
    OnlyStrategyCashReservationExecutionProjection,
    OnlyStrategyLedgerExecutionProjection,
    OnlyTradeExecutionPlanningContext,
    OnlyTradeExecutionTransactionPlanner,
    OnlyValuationExecutionState,
)
from onlyalpha.fee import OnlyFeeBreakdown, OnlyFeeInstruction, OnlyFeeStatus
from onlyalpha.market.models import OnlyPositionEffect
from onlyalpha.market.runtime_rules import (
    OnlyCashInstruction,
    OnlyCompiledMarketRuleIdentity,
    OnlyPositionInstruction,
    OnlySettlementRuntimeInstruction,
    OnlyTradeApplicationInstruction,
)
from onlyalpha.position.enums import OnlyPositionMode, OnlyPositionSide
from onlyalpha.position.identifiers import OnlyPositionAllocationId
from onlyalpha.position.keys import OnlyPositionAllocationKey, OnlyPositionKey
from onlyalpha.strategy.identifiers import OnlyStrategyId

from .transaction_factory import only_test_generic_t0_cash_buy_open_projections


def only_test_generic_t0_trade_planning_context(**changes: object) -> OnlyTradeExecutionPlanningContext:
    projections = only_test_generic_t0_cash_buy_open_projections()
    order_projection = _one(projections, OnlyOrderExecutionProjection)
    account_projection = _one(projections, OnlyAccountExecutionProjection)
    ledger_projection = _one(projections, OnlyStrategyLedgerExecutionProjection)
    account_reservation = _one(projections, OnlyAccountCashReservationExecutionProjection).before
    strategy_reservation = _one(projections, OnlyStrategyCashReservationExecutionProjection).before
    risk_reservation = _one(projections, OnlyRiskReservationExecutionProjection).before
    risk = _one(projections, OnlyRiskExecutionProjection).before
    assert account_reservation is not None
    assert strategy_reservation is not None
    assert risk_reservation is not None
    assert risk is not None
    order = order_projection.before
    timestamp = order.updated_at
    day = OnlyTradingDay(date(2026, 1, 1))
    currency = account_projection.before.base_currency
    reserved = OnlyMoney(Decimal("20.00"), currency)
    account_before = replace(
        account_projection.before,
        frozen_cash=reserved,
        available_cash=OnlyMoney(Decimal("80.00"), currency),
        available_margin=OnlyMoney(Decimal("80.00"), currency),
    )
    ledger_before = replace(
        ledger_projection.before,
        cash_reserved=reserved,
        cash_available=OnlyMoney(Decimal("80.00"), currency),
    )
    position_key = OnlyPositionKey(
        order.runtime_id,
        order.account_id,
        order.instrument_id,
        OnlyPositionSide.LONG,
        OnlyPositionMode.NETTING,
    )
    allocation_key = OnlyPositionAllocationKey(
        order.runtime_id,
        order.account_id,
        order.cluster_id,
        order.instrument_id,
        OnlyPositionSide.LONG,
    )
    scope = OnlyExecutionPositionScope(
        order.runtime_id,
        order.account_id,
        order.cluster_id,
        order.instrument_id,
        OnlyPositionSide.LONG,
        OnlyPositionEffect.OPEN,
        OnlyPositionMode.NETTING,
        position_key,
        allocation_key,
        OnlyPositionScopeResolutionSource.MARKET_RULE_INSTRUCTION,
    )
    fill = order_projection.fill
    update = OnlyBrokerTradeUpdate(
        runtime_id=order.runtime_id,
        gateway_id=OnlyBrokerGatewayId("gateway"),
        account_id=order.account_id,
        update_id=OnlyBrokerUpdateId("update"),
        source_sequence=7,
        ts_event=timestamp,
        ts_init=timestamp,
        correlation_id="correlation",
        causation_id="causation",
        order_id=order.order_id,
        fill=fill,
    )
    settlement = OnlySettlementRuntimeInstruction(
        "settlement",
        str(order.instrument_id),
        str(fill.trade_id),
        fill.quantity.value,
        Decimal("20.00"),
        day,
        day,
        day,
        day,
        str(order.account_id),
        str(order.order_id),
    )
    identity = OnlyCompiledMarketRuleIdentity(
        "GENERIC_T0_CASH",
        "1",
        day.value,
        OnlyRuntimeMode.BACKTEST,
        str(order.instrument_id),
        "XSHG",
        "reference",
        "resolved",
        "compiled",
    )
    instruction = OnlyTradeApplicationInstruction(
        OnlyPositionInstruction(
            str(order.instrument_id),
            OnlyPositionSide.LONG.value,
            OnlyPositionEffect.OPEN,
            fill.quantity.value,
            fill.price.value,
            "SETTLED",
            str(order.order_id),
            str(fill.trade_id),
        ),
        settlement,
        None,
        OnlyCashInstruction(currency.code, Decimal("-20.00"), day, True),
        identity,
    )
    fee = OnlyFeeInstruction(
        "fee-instruction",
        str(order.runtime_id),
        str(order.cluster_id),
        str(order.account_id),
        str(order.order_id),
        str(fill.trade_id),
        OnlyFeeBreakdown.empty(currency, OnlyFeeStatus.CONFIRMED),
        "MARKET_RULE",
        timestamp.to_datetime(),
        "fee-idempotency",
    )
    context = OnlyTradeExecutionPlanningContext(
        update=update,
        prepared_at=timestamp,
        engine_id=OnlyEngineId("engine"),
        strategy_id=OnlyStrategyId("strategy"),
        processing_sequence=3,
        trading_day=day,
        contract_multiplier=OnlyMultiplier(Decimal(1), 0),
        position_scope=scope,
        trade_instruction=instruction,
        fee_instruction=fee,
        order_before=order,
        position_before=None,
        allocation_before=None,
        settlement_before=None,
        fee_before=None,
        account_before=account_before,
        strategy_ledger_before=ledger_before,
        account_cash_reservation_before=account_reservation,
        strategy_cash_reservation_before=strategy_reservation,
        risk_reservation_before=risk_reservation,
        risk_before=risk,
        valuation_before=OnlyValuationExecutionState(
            order.account_id,
            timestamp,
            account_before.cash_balance,
            account_before.position_market_value,
            account_before.unrealized_pnl,
            account_before.equity,
            1,
        ),
        position_creation=OnlyPositionCreationAuthority(
            OnlyPositionId(f"POS-{order.runtime_id}-{order.account_id}-{order.instrument_id}-LONG-00000001"),
            1,
        ),
        allocation_creation=OnlyAllocationCreationAuthority(
            OnlyPositionAllocationId(
                f"ALLOC-{order.runtime_id}-{order.account_id}-{order.cluster_id}-{order.instrument_id}-00000001"
            ),
            1,
        ),
    )
    return replace(context, **changes)


def only_test_generic_t0_planned_trade():
    context = only_test_generic_t0_trade_planning_context()
    return OnlyTradeExecutionTransactionPlanner._planned_trade(context)


def only_test_generic_t0_expected_reductions():
    prepared = only_test_generic_t0_prepared_transaction()
    return prepared.projections


def only_test_generic_t0_prepared_transaction() -> OnlyPreparedExecutionTransaction:
    return OnlyTradeExecutionTransactionPlanner().prepare(only_test_generic_t0_trade_planning_context())


def _one(items: tuple[object, ...], expected: type):
    return next(item for item in items if isinstance(item, expected))


__all__ = [name for name in globals() if name.startswith("only_test_")]
