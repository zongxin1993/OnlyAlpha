from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.identifiers import OnlyTradeId
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.execution import OnlyTradeExecutionTransactionPlanner
from onlyalpha.execution.reducers import OnlyOrderTradeReducer
from tests.execution.factories.trade_planning_factory import only_test_generic_t0_trade_planning_context


def _before(status: OnlyOrderStatus = OnlyOrderStatus.ACCEPTED):
    state = only_test_generic_t0_trade_planning_context().order_before
    return replace(
        state,
        status=status,
        quantity=OnlyQuantity(Decimal("10"), 0),
        filled_quantity=OnlyQuantity(Decimal(0), 0),
        remaining_quantity=OnlyQuantity(Decimal("10"), 0),
        average_fill_price=None,
        fill_count=0,
        cumulative_price_quantity=Decimal(0),
        last_trade_id=None,
        filled_at=None,
    )


def _trade(quantity: str, trade_id: str, sequence: int, price: str = "10.00"):
    context = only_test_generic_t0_trade_planning_context()
    base = OnlyTradeExecutionTransactionPlanner._planned_trade(context)
    source_sequence = sequence + 100
    fill = replace(
        base.fill,
        trade_id=OnlyTradeId(trade_id),
        quantity=OnlyQuantity(Decimal(quantity), 0),
        price=OnlyPrice(Decimal(price), 2),
        external_sequence=source_sequence,
    )
    return replace(
        base,
        trade_id=fill.trade_id,
        quantity=fill.quantity,
        price=fill.price,
        fill=fill,
        source_sequence=source_sequence,
        stable_order=(source_sequence, fill.ts_event.unix_nanos, trade_id),
    )


@pytest.mark.parametrize("status", (OnlyOrderStatus.SUBMITTED, OnlyOrderStatus.ACCEPTED))
def test_first_partial_fill_enters_partial_state(status: OnlyOrderStatus) -> None:
    result = OnlyOrderTradeReducer().reduce(_before(status), _trade("3", "trade-1", 1), projection_sequence=1)
    assert result.after.status is OnlyOrderStatus.PARTIALLY_FILLED
    assert result.after.filled_quantity.value == 3
    assert result.after.remaining_quantity.value == 7
    assert result.after.fill_count == 1
    assert result.after.last_trade_id == OnlyTradeId("trade-1")
    assert result.after.filled_at is None
    assert result.event_intents[0].event_type.value == "ORDER_PARTIALLY_FILLED"


def test_three_fills_conserve_quantity_and_only_final_fill_is_terminal() -> None:
    reducer = OnlyOrderTradeReducer()
    first = reducer.reduce(_before(), _trade("3", "trade-1", 1), projection_sequence=1).after
    second = reducer.reduce(first, _trade("4", "trade-2", 2), projection_sequence=1).after
    final = reducer.reduce(second, _trade("3", "trade-3", 3), projection_sequence=1)
    assert second.status is OnlyOrderStatus.PARTIALLY_FILLED and second.fill_count == 2
    assert final.after.status is OnlyOrderStatus.FILLED and final.after.fill_count == 3
    assert final.after.filled_quantity.value + final.after.remaining_quantity.value == final.after.quantity.value
    assert final.after.filled_at == final.projection.fill.ts_event
    assert final.event_intents[0].event_type.value == "ORDER_FILLED"


def test_pending_cancel_preserves_status_until_final_fill() -> None:
    reducer = OnlyOrderTradeReducer()
    partial = reducer.reduce(_before(OnlyOrderStatus.PENDING_CANCEL), _trade("4", "trade-1", 1), projection_sequence=1)
    assert partial.after.status is OnlyOrderStatus.PENDING_CANCEL
    assert partial.event_intents[0].event_type.value == "ORDER_PARTIALLY_FILLED"
    final = reducer.reduce(partial.after, _trade("6", "trade-2", 2), projection_sequence=1)
    assert final.after.status is OnlyOrderStatus.FILLED
    assert final.event_intents[0].event_type.value == "ORDER_FILLED"


@pytest.mark.parametrize(
    "status",
    (
        OnlyOrderStatus.CREATED,
        OnlyOrderStatus.FILLED,
        OnlyOrderStatus.CANCELLED,
        OnlyOrderStatus.EXPIRED,
        OnlyOrderStatus.REJECTED,
        OnlyOrderStatus.FAILED,
    ),
)
def test_terminal_and_unsubmitted_states_reject_fill(status: OnlyOrderStatus) -> None:
    before = _before() if status is OnlyOrderStatus.FILLED else _before(status)
    if status is OnlyOrderStatus.FILLED:
        before = replace(
            before,
            status=OnlyOrderStatus.FILLED,
            filled_quantity=before.quantity,
            remaining_quantity=OnlyQuantity(Decimal(0), 0),
            average_fill_price=OnlyPrice(Decimal("10.00"), 2),
            fill_count=1,
            cumulative_price_quantity=Decimal("100.00"),
            last_trade_id=OnlyTradeId("existing"),
            filled_at=before.updated_at,
        )
    with pytest.raises(ValueError, match="does not accept"):
        OnlyOrderTradeReducer().reduce(before, _trade("1", "trade-new", 2), projection_sequence=1)


def test_overfill_rejected_without_mutating_before() -> None:
    before = _before()
    with pytest.raises(ValueError, match="remaining"):
        OnlyOrderTradeReducer().reduce(before, _trade("11", "trade-over", 1), projection_sequence=1)
    assert before.filled_quantity.value == 0 and before.fill_count == 0
