from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal
from typing import Any, cast

import pytest

from onlyalpha.account.enums import OnlyAccountReservationState
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderStatus, OnlyOrderType
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyQuantity
from onlyalpha.execution import (
    OnlyExecutionPositionScope,
    OnlyPositionScopeResolutionSource,
    OnlyTradeExecutionPlanningContext,
    OnlyTradeExecutionPlanningError,
    OnlyTradeExecutionPlanningErrorCode,
    OnlyTradeExecutionTransactionPlanner,
)
from onlyalpha.fee import OnlyFeeBreakdown, OnlyFeeStatus
from onlyalpha.position.enums import OnlyPositionMode, OnlyPositionSide
from onlyalpha.position.keys import OnlyPositionAllocationKey, OnlyPositionKey

from .support.generic_t0_trade_harness import (
    OnlyTestGenericT0Scenario,
    _environment,
    _prepare_environment,
    _trade_update,
    only_test_real_trade_planning_context,
)
from .support.manager_authority_digest import only_test_runtime_authority_digest

Mutation = Callable[[OnlyTradeExecutionPlanningContext], OnlyTradeExecutionPlanningContext]


def _unsupported_profile(context: OnlyTradeExecutionPlanningContext) -> OnlyTradeExecutionPlanningContext:
    identity = replace(context.trade_instruction.compiled_identity, profile_id="OTHER")
    return replace(context, trade_instruction=replace(context.trade_instruction, compiled_identity=identity))


def _order_type(context: OnlyTradeExecutionPlanningContext) -> OnlyTradeExecutionPlanningContext:
    return replace(context, order_before=replace(context.order_before, order_type=OnlyOrderType.MARKET))


def _order_side(context: OnlyTradeExecutionPlanningContext) -> OnlyTradeExecutionPlanningContext:
    return replace(context, order_before=replace(context.order_before, side=OnlyOrderSide.SELL))


def _offset(context: OnlyTradeExecutionPlanningContext) -> OnlyTradeExecutionPlanningContext:
    return replace(context, order_before=replace(context.order_before, offset=OnlyOffset.CLOSE))


def _scope(
    context: OnlyTradeExecutionPlanningContext,
    side: OnlyPositionSide,
    mode: OnlyPositionMode,
) -> OnlyExecutionPositionScope:
    order = context.order_before
    return OnlyExecutionPositionScope(
        order.runtime_id,
        order.account_id,
        order.cluster_id,
        order.instrument_id,
        side,
        context.position_scope.position_effect,
        mode,
        OnlyPositionKey(order.runtime_id, order.account_id, order.instrument_id, side, mode),
        OnlyPositionAllocationKey(order.runtime_id, order.account_id, order.cluster_id, order.instrument_id, side),
        OnlyPositionScopeResolutionSource.MARKET_RULE_INSTRUCTION,
    )


def _position_side(context: OnlyTradeExecutionPlanningContext) -> OnlyTradeExecutionPlanningContext:
    return replace(context, position_scope=_scope(context, OnlyPositionSide.SHORT, OnlyPositionMode.NETTING))


def _position_mode(context: OnlyTradeExecutionPlanningContext) -> OnlyTradeExecutionPlanningContext:
    return replace(context, position_scope=_scope(context, OnlyPositionSide.LONG, OnlyPositionMode.HEDGING))


def _margin(context: OnlyTradeExecutionPlanningContext) -> OnlyTradeExecutionPlanningContext:
    return replace(context, margin_reservation_before=cast(Any, object()))


def _position_reservation(context: OnlyTradeExecutionPlanningContext) -> OnlyTradeExecutionPlanningContext:
    return replace(context, position_reservation_before=cast(Any, object()))


def _partial_fill(context: OnlyTradeExecutionPlanningContext) -> OnlyTradeExecutionPlanningContext:
    fill = replace(context.update.fill, quantity=OnlyQuantity(Decimal("1"), context.update.fill.quantity.precision))
    return replace(context, update=replace(context.update, fill=fill))


def _scope_mismatch(context: OnlyTradeExecutionPlanningContext) -> OnlyTradeExecutionPlanningContext:
    return replace(context, update=replace(context.update, runtime_id=OnlyRuntimeId("other-runtime")))


def _currency(context: OnlyTradeExecutionPlanningContext) -> OnlyTradeExecutionPlanningContext:
    usd = OnlyCurrency("USD", 2)
    breakdown = OnlyFeeBreakdown.empty(usd, OnlyFeeStatus.CONFIRMED)
    return replace(context, fee_instruction=replace(context.fee_instruction, fee_breakdown=breakdown))


def _missing_before(context: OnlyTradeExecutionPlanningContext) -> OnlyTradeExecutionPlanningContext:
    return replace(context, risk_before=cast(Any, None))


def _missing_creation(context: OnlyTradeExecutionPlanningContext) -> OnlyTradeExecutionPlanningContext:
    return replace(context, position_creation=None)


def _unexpected_creation(context: OnlyTradeExecutionPlanningContext) -> OnlyTradeExecutionPlanningContext:
    prepared = OnlyTradeExecutionTransactionPlanner().prepare(context)
    position = next(item for item in prepared.projections if item.identity.component.value == "POSITION")
    return replace(
        context,
        position_before=replace(position.after, last_trade_sequence=None, last_trade_order=None),
    )


def _stale(context: OnlyTradeExecutionPlanningContext) -> OnlyTradeExecutionPlanningContext:
    sequence = context.order_before.last_external_sequence or 0
    fill = replace(context.update.fill, external_sequence=sequence)
    return replace(context, update=replace(context.update, source_sequence=sequence, fill=fill))


def _invalid_order(context: OnlyTradeExecutionPlanningContext) -> OnlyTradeExecutionPlanningContext:
    return replace(context, order_before=replace(context.order_before, status=OnlyOrderStatus.CREATED))


def _invalid_reservation(context: OnlyTradeExecutionPlanningContext) -> OnlyTradeExecutionPlanningContext:
    before = context.account_cash_reservation_before
    consumed = before.reserved_amount
    return replace(
        context,
        account_cash_reservation_before=replace(
            before,
            consumed_amount=consumed,
            remaining_amount=OnlyMoney(Decimal(0), consumed.currency),
            state=OnlyAccountReservationState.CONSUMED,
        ),
    )


def _reduction_failure(context: OnlyTradeExecutionPlanningContext) -> OnlyTradeExecutionPlanningContext:
    before = context.account_cash_reservation_before
    one = OnlyMoney(Decimal("1.00"), before.reserved_amount.currency)
    return replace(context, account_cash_reservation_before=replace(before, reserved_amount=one, remaining_amount=one))


CASES: tuple[tuple[OnlyTradeExecutionPlanningErrorCode, Mutation], ...] = (
    (OnlyTradeExecutionPlanningErrorCode.UNSUPPORTED_MARKET_PROFILE, _unsupported_profile),
    (OnlyTradeExecutionPlanningErrorCode.UNSUPPORTED_ORDER_TYPE, _order_type),
    (OnlyTradeExecutionPlanningErrorCode.UNSUPPORTED_ORDER_SIDE, _order_side),
    (OnlyTradeExecutionPlanningErrorCode.UNSUPPORTED_OFFSET, _offset),
    (OnlyTradeExecutionPlanningErrorCode.UNSUPPORTED_POSITION_SIDE, _position_side),
    (OnlyTradeExecutionPlanningErrorCode.UNSUPPORTED_POSITION_MODE, _position_mode),
    (OnlyTradeExecutionPlanningErrorCode.PARTIAL_FILL_UNSUPPORTED, _partial_fill),
    (OnlyTradeExecutionPlanningErrorCode.MARGIN_UNSUPPORTED, _margin),
    (OnlyTradeExecutionPlanningErrorCode.POSITION_RESERVATION_FORBIDDEN, _position_reservation),
    (OnlyTradeExecutionPlanningErrorCode.SCOPE_MISMATCH, _scope_mismatch),
    (OnlyTradeExecutionPlanningErrorCode.CURRENCY_MISMATCH, _currency),
    (OnlyTradeExecutionPlanningErrorCode.MISSING_BEFORE_STATE, _missing_before),
    (OnlyTradeExecutionPlanningErrorCode.MISSING_CREATION_AUTHORITY, _missing_creation),
    (OnlyTradeExecutionPlanningErrorCode.UNEXPECTED_CREATION_AUTHORITY, _unexpected_creation),
    (OnlyTradeExecutionPlanningErrorCode.STALE_EXTERNAL_SEQUENCE, _stale),
    (OnlyTradeExecutionPlanningErrorCode.INVALID_ORDER_STATE, _invalid_order),
    (OnlyTradeExecutionPlanningErrorCode.INVALID_RESERVATION_STATE, _invalid_reservation),
    (OnlyTradeExecutionPlanningErrorCode.REDUCTION_INVARIANT_FAILED, _reduction_failure),
)


@pytest.mark.parametrize(("code", "mutate"), CASES, ids=lambda item: getattr(item, "value", None))
def test_every_stable_planner_error_is_atomic(code: OnlyTradeExecutionPlanningErrorCode, mutate: Mutation) -> None:
    scenario = OnlyTestGenericT0Scenario(f"failure-{code.value.lower()}")
    env = _environment(scenario)
    _prepare_environment(env, scenario)
    context = only_test_real_trade_planning_context(env, _trade_update(env, scenario))
    before = only_test_runtime_authority_digest(env)

    with pytest.raises(OnlyTradeExecutionPlanningError) as raised:
        OnlyTradeExecutionTransactionPlanner().prepare(mutate(context))

    assert raised.value.code is code
    assert only_test_runtime_authority_digest(env) == before


FAILURE_STAGES = (
    "context_validation",
    "planned_trade",
    "order",
    "position",
    "allocation",
    "settlement",
    "fee",
    "account",
    "strategy_ledger",
    "account_reservation",
    "strategy_reservation",
    "risk_reservation",
    "risk",
    "valuation",
    "fact_draft",
    "projection_finalization",
    "precondition",
    "event",
    "prepared_transaction",
)


@pytest.mark.parametrize("stage", FAILURE_STAGES)
def test_every_planning_stage_failure_has_no_partial_result_or_external_side_effect(
    stage: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = OnlyTestGenericT0Scenario(f"fault-{stage}")
    env = _environment(scenario)
    _prepare_environment(env, scenario)
    context = only_test_real_trade_planning_context(env, _trade_update(env, scenario))
    before = only_test_runtime_authority_digest(env)
    if stage == "context_validation":
        context = _unsupported_profile(context)
    else:
        _inject_failure(stage, monkeypatch)

    with pytest.raises(OnlyTradeExecutionPlanningError):
        OnlyTradeExecutionTransactionPlanner().prepare(context)

    assert only_test_runtime_authority_digest(env) == before


def _inject_failure(stage: str, monkeypatch: pytest.MonkeyPatch) -> None:
    planner_module = importlib.import_module("onlyalpha.execution.trade_planner")
    projection_builder_module = importlib.import_module("onlyalpha.execution.projection_builder")

    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise ValueError(f"injected {stage} failure")

    reducer_names = {
        "order": "OnlyOrderTradeReducer",
        "position": "OnlyPositionTradeReducer",
        "allocation": "OnlyAllocationTradeReducer",
        "settlement": "OnlySettlementTradeReducer",
        "fee": "OnlyFeeTradeReducer",
        "account": "OnlyAccountTradeReducer",
        "strategy_ledger": "OnlyStrategyLedgerTradeReducer",
        "account_reservation": "OnlyAccountCashReservationTradeReducer",
        "strategy_reservation": "OnlyStrategyCashReservationTradeReducer",
        "risk_reservation": "OnlyRiskReservationTradeReducer",
        "risk": "OnlyRiskTradeReducer",
        "valuation": "OnlyValuationTradeReducer",
    }
    if stage in reducer_names:
        monkeypatch.setattr(planner_module, reducer_names[stage], lambda: type("FailReducer", (), {"reduce": fail})())
    elif stage == "planned_trade":
        monkeypatch.setattr(planner_module.OnlyTradeExecutionTransactionPlanner, "_planned_trade", staticmethod(fail))
    elif stage == "fact_draft":
        monkeypatch.setattr(planner_module.OnlyTradeExecutionTransactionPlanner, "_fact", staticmethod(fail))
    elif stage == "projection_finalization":
        monkeypatch.setattr(projection_builder_module.OnlyExecutionProjectionBuilder, "finalize", fail)
    elif stage == "precondition":
        monkeypatch.setattr(planner_module, "OnlyExecutionPrecondition", fail)
    elif stage == "event":
        monkeypatch.setattr(planner_module.OnlyTradeExecutionTransactionPlanner, "_events", staticmethod(fail))
    elif stage == "prepared_transaction":
        monkeypatch.setattr(planner_module, "OnlyPreparedExecutionTransaction", fail)
    else:
        raise AssertionError(f"unknown failure stage: {stage}")
