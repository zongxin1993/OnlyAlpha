from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from onlyalpha.domain.value import OnlyMoney, OnlyQuantity
from onlyalpha.execution import (
    OnlyAccountCashReservationExecutionProjection,
    OnlyAccountExecutionProjection,
    OnlyAllocationExecutionProjection,
    OnlyFeeExecutionProjection,
    OnlyOrderExecutionProjection,
    OnlyOrderFeeAccrualExecutionProjection,
    OnlyPositionExecutionProjection,
    OnlyRiskExecutionProjection,
    OnlyRiskReservationExecutionProjection,
    OnlySettlementExecutionProjection,
    OnlyStrategyCashReservationExecutionProjection,
    OnlyStrategyLedgerExecutionProjection,
    OnlyTradeExecutionTransactionPlanner,
    OnlyValuationExecutionProjection,
    only_encode_execution_projection,
)
from onlyalpha.execution.planning_results import OnlyTradeReduction
from onlyalpha.execution.reducers import (
    OnlyAccountCashReservationTradeReducer,
    OnlyRiskReservationTradeReducer,
    OnlyStrategyCashReservationTradeReducer,
)

from ..factories.trade_planning_factory import only_test_generic_t0_trade_planning_context


def _reductions() -> tuple[object, ...]:
    context = only_test_generic_t0_trade_planning_context()
    prepared = OnlyTradeExecutionTransactionPlanner().prepare(context)
    return tuple(OnlyTradeReduction(item) for item in prepared.projections)


def test_every_reducer_matches_complete_prepared_projection_and_keeps_inputs_immutable() -> None:
    context = only_test_generic_t0_trade_planning_context()
    before = context
    expected = OnlyTradeExecutionTransactionPlanner().prepare(context).projections
    reductions = _reductions()

    for reduction, projection in zip(reductions, expected, strict=True):
        assert type(reduction.projection) is type(projection)
        assert reduction.projection.before == projection.before
        assert reduction.projection.after == projection.after
    assert context == before
    for result in reductions:
        projection = result.projection
        assert projection.identity.result_version == projection.after.version
        assert len(projection.identity.expected_state_hash) == 64
        assert len(projection.identity.result_state_hash) == 64
        assert len(projection.identity.payload_hash) == 64


def test_every_reducer_is_byte_deterministic_across_100_fresh_instances() -> None:
    baseline = tuple(only_encode_execution_projection(item.projection) for item in _reductions())
    for _ in range(100):
        assert tuple(only_encode_execution_projection(item.projection) for item in _reductions()) == baseline


def test_cash_reservation_reducers_reject_insufficient_authority_without_mutation() -> None:
    context = only_test_generic_t0_trade_planning_context()
    trade = OnlyTradeExecutionTransactionPlanner._planned_trade(context)
    one = OnlyMoney(Decimal("1.00"), trade.authoritative_fee.currency)
    account_before = replace(
        context.account_cash_reservation_before,
        reserved_amount=one,
        remaining_amount=one,
    )
    strategy_before = replace(
        context.strategy_cash_reservation_before,
        estimated_notional=one,
        estimated_fee=OnlyMoney(Decimal(0), one.currency),
        reserved_amount=one,
        remaining_amount=one,
    )
    with pytest.raises(ValueError, match="smaller"):
        OnlyAccountCashReservationTradeReducer().reduce(account_before, trade, projection_sequence=8)
    with pytest.raises(ValueError, match="smaller"):
        OnlyStrategyCashReservationTradeReducer().reduce(strategy_before, trade, projection_sequence=9)
    assert account_before.remaining_amount == one
    assert strategy_before.remaining_amount == one


def test_risk_reducer_rejects_quantity_and_notional_under_reservation() -> None:
    context = only_test_generic_t0_trade_planning_context()
    trade = OnlyTradeExecutionTransactionPlanner._planned_trade(context)
    before = context.risk_reservation_before
    zero_quantity = OnlyQuantity(Decimal(0), before.remaining_quantity.precision)
    invalid = replace(
        before,
        consumed_quantity=before.reserved_quantity,
        consumed_notional=before.reserved_notional,
        remaining_quantity=zero_quantity,
        remaining_notional=OnlyMoney(Decimal(0), trade.authoritative_fee.currency),
    )
    with pytest.raises(ValueError, match="quantity"):
        OnlyRiskReservationTradeReducer().reduce(invalid, trade, projection_sequence=10)


@pytest.mark.parametrize(
    "projection_type",
    (
        OnlyOrderExecutionProjection,
        OnlyPositionExecutionProjection,
        OnlyAllocationExecutionProjection,
        OnlySettlementExecutionProjection,
        OnlyOrderFeeAccrualExecutionProjection,
        OnlyFeeExecutionProjection,
        OnlyAccountExecutionProjection,
        OnlyStrategyLedgerExecutionProjection,
        OnlyAccountCashReservationExecutionProjection,
        OnlyStrategyCashReservationExecutionProjection,
        OnlyRiskReservationExecutionProjection,
        OnlyRiskExecutionProjection,
        OnlyValuationExecutionProjection,
    ),
)
def test_each_reducer_emits_one_typed_projection(projection_type: type) -> None:
    assert sum(isinstance(item.projection, projection_type) for item in _reductions()) == 1
