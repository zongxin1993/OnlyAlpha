from __future__ import annotations

from decimal import Decimal

import pytest

from onlyalpha.execution import (
    OnlyAccountCashReservationExecutionProjection,
    OnlyAccountExecutionProjection,
    OnlyAllocationExecutionProjection,
    OnlyExecutionProcessingStatus,
    OnlyFeeExecutionProjection,
    OnlyOrderExecutionProjection,
    OnlyPositionExecutionProjection,
    OnlyRiskExecutionProjection,
    OnlyRiskReservationExecutionProjection,
    OnlySettlementExecutionProjection,
    OnlyStrategyCashReservationExecutionProjection,
    OnlyStrategyLedgerExecutionProjection,
    OnlyValuationExecutionProjection,
)

from .support.generic_t0_trade_harness import (
    OnlyTestGenericT0Scenario,
    only_test_generic_t0_manager_parity,
    only_test_projection_after,
)

SCENARIOS = (
    OnlyTestGenericT0Scenario("new-zero-fee", fee_enabled=False),
    OnlyTestGenericT0Scenario("new-nonzero-fee"),
    OnlyTestGenericT0Scenario("excess-reservation", fill_price="9.90"),
    OnlyTestGenericT0Scenario("existing-position", fill_price="12.00", existing_position=True),
)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item.name)
def test_real_manager_after_authority_equals_planner_projection(
    scenario: OnlyTestGenericT0Scenario,
) -> None:
    result = only_test_generic_t0_manager_parity(scenario)
    assert result.legacy_result.status is OnlyExecutionProcessingStatus.APPLIED
    assert result.planner_before == result.planner_after
    planned = {item.identity.component: only_test_projection_after(item) for item in result.prepared.projections}
    assert planned == dict(result.legacy_states)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item.name)
def test_real_manager_parity_covers_complete_economic_and_lifecycle_authority(
    scenario: OnlyTestGenericT0Scenario,
) -> None:
    result = only_test_generic_t0_manager_parity(scenario)
    projections = result.prepared.projections
    order = _one(projections, OnlyOrderExecutionProjection)
    position = _one(projections, OnlyPositionExecutionProjection)
    allocation = _one(projections, OnlyAllocationExecutionProjection)
    settlement = _one(projections, OnlySettlementExecutionProjection)
    fee = _one(projections, OnlyFeeExecutionProjection)
    account = _one(projections, OnlyAccountExecutionProjection)
    ledger = _one(projections, OnlyStrategyLedgerExecutionProjection)
    account_reservation = _one(projections, OnlyAccountCashReservationExecutionProjection)
    strategy_reservation = _one(projections, OnlyStrategyCashReservationExecutionProjection)
    risk_reservation = _one(projections, OnlyRiskReservationExecutionProjection)
    risk = _one(projections, OnlyRiskExecutionProjection)
    valuation = _one(projections, OnlyValuationExecutionProjection)

    quantity = result.context.update.fill.quantity
    assert order.after.filled_quantity.value - order.before.filled_quantity.value == quantity.value
    assert position.after.total_quantity.value - _quantity_before(position.before) == quantity.value
    assert allocation.after.total_quantity.value - _quantity_before(allocation.before) == quantity.value
    assert fee.after.authoritative_total == result.context.fee_instruction.fee_breakdown.total
    assert position.after.fees.amount - _money_before(position.before, "fees") == fee.after.authoritative_total.amount
    assert (
        allocation.after.fees.amount - _money_before(allocation.before, "fees") == fee.after.authoritative_total.amount
    )
    assert account.after.fees.amount - account.before.fees.amount == fee.after.authoritative_total.amount
    assert ledger.after.fees.amount - ledger.before.fees.amount == fee.after.authoritative_total.amount
    cost = result.context.trade_instruction.cash_instruction.amount.copy_abs() + fee.after.authoritative_total.amount
    assert account_reservation.after.consumed_amount.amount == cost
    assert strategy_reservation.after.consumed_amount.amount == cost
    assert account_reservation.after.remaining_amount.amount == 0
    assert strategy_reservation.after.remaining_amount.amount == 0
    assert account_reservation.after.state.value == "RELEASED"
    assert strategy_reservation.after.state.value == "RELEASED"
    assert risk_reservation.after.state.value == "CONSUMED"
    assert risk.after.reserved_quantity == 0
    assert settlement.records[-1].sequence == result.context.settlement_record_sequence + 1
    if fee.after.records:
        assert fee.after.records[0].record_id.endswith(f"{result.context.fee_record_sequence + 1:08d}")
    assert valuation.after.cash == account.after.cash_balance
    assert valuation.after.position_market_value == account.after.position_market_value
    assert valuation.after.equity == account.after.equity == ledger.after.equity
    assert order.after.updated_at == result.context.update.ts_init
    assert order.after.filled_at == result.context.update.ts_event
    assert position.after.updated_at == result.context.update.ts_event
    assert allocation.after.updated_at == result.context.update.ts_event
    assert account.after.updated_at == result.context.update.ts_init
    assert account.after.valuation_time == result.context.update.ts_init
    assert ledger.after.updated_at == result.context.update.ts_init
    assert ledger.after.valuation_time == result.context.update.ts_event
    assert risk.after.ts_event == result.context.update.ts_init
    assert risk.after.ts_init == result.context.update.ts_init
    assert valuation.after.valuation_time == result.context.update.ts_init


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item.name)
def test_legacy_and_durable_events_have_equivalent_business_semantics(
    scenario: OnlyTestGenericT0Scenario,
) -> None:
    result = only_test_generic_t0_manager_parity(scenario)
    legacy_events = result.legacy_result.generated_events
    planned_events = result.prepared.outbox_events
    aliases = {
        "ACCOUNT_RESERVATION_CONSUMED": "ACCOUNT_CASH_RESERVATION_CONSUMED",
        "ACCOUNT_RESERVATION_RELEASED": "ACCOUNT_CASH_RESERVATION_RELEASED",
    }
    legacy_types = [aliases.get(event.event_type.value, event.event_type.value) for event in legacy_events]
    legacy_business_types = [value for value in legacy_types if value != "EXECUTION_UPDATE_APPLIED"]
    planner_business_types = [
        event.event_type.value
        for event in planned_events
        if event.event_type.value not in {"SETTLEMENT_UPDATED", "FEE_RECORDED", "RISK_STATE_UPDATED"}
    ]

    assert planner_business_types == legacy_business_types
    legacy_by_type = {
        aliases.get(event.event_type.value, event.event_type.value): event
        for event in legacy_events
        if event.event_type.value != "EXECUTION_UPDATE_APPLIED"
    }
    planned_by_type = {event.event_type.value: event for event in planned_events}
    for event_type in legacy_business_types:
        assert planned_by_type[event_type].timestamp == legacy_by_type[event_type].timestamp
        assert planned_by_type[event_type].ts_init == legacy_by_type[event_type].ts_init
    assert all(event.runtime_id == result.context.update.runtime_id for event in planned_events)
    assert all(event.cluster_id == result.context.order_before.cluster_id for event in planned_events)
    assert all(event.metadata["broker_update_id"] == str(result.context.update.update_id) for event in planned_events)

    planned_payloads = {event.event_type.value: event.payload for event in planned_events}
    order_after = only_test_projection_after(_one(result.prepared.projections, OnlyOrderExecutionProjection))
    position_after = only_test_projection_after(_one(result.prepared.projections, OnlyPositionExecutionProjection))
    assert planned_payloads["ORDER_FILLED"] == order_after.to_dict()
    assert planned_payloads[planner_business_types[1]] == position_after.to_dict()


def _one(items: tuple[object, ...], expected: type):
    return next(item for item in items if isinstance(item, expected))


def _quantity_before(value: object | None) -> Decimal:
    return Decimal(0) if value is None else value.total_quantity.value


def _money_before(value: object | None, field: str) -> Decimal:
    return Decimal(0) if value is None else getattr(value, field).amount
