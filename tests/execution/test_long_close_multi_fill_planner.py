from decimal import Decimal

from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.execution.committed import OnlyCommittedExecutionFact
from onlyalpha.execution.enums import OnlyExecutionOperationKind, OnlyExecutionProcessingStatus
from onlyalpha.position.enums import OnlyPositionReservationState, OnlyPositionStatus
from onlyalpha.risk.enums import OnlyRiskReservationState
from tests.execution.support.generic_t0_trade_harness import (
    only_test_generic_t0_long_close_context,
    only_test_generic_t0_long_close_update,
)


def test_long_close_300_400_300_is_three_sequential_durable_transactions() -> None:
    environment, first_context, _ = only_test_generic_t0_long_close_context(
        open_quantity="1000",
        close_quantity="1000",
        fill_quantity="300",
        fill_price="12.00",
    )
    processor = environment.runtime.execution_processor

    first = processor.process(first_context.update)
    second_update = only_test_generic_t0_long_close_update(
        environment,
        first_context.update.order_id,
        suffix="second",
        fill_quantity="400",
        fill_price="9.00",
    )
    second = processor.process(second_update)
    third_update = only_test_generic_t0_long_close_update(
        environment,
        first_context.update.order_id,
        suffix="third",
        fill_quantity="300",
        fill_price="10.00",
    )
    third = processor.process(third_update)

    assert (first.status, second.status, third.status) == (
        OnlyExecutionProcessingStatus.APPLIED,
        OnlyExecutionProcessingStatus.APPLIED,
        OnlyExecutionProcessingStatus.APPLIED,
    )
    transactions = environment.runtime.execution_transaction_query.transactions_for_order(
        first_context.update.runtime_id,
        first_context.update.order_id,
    )
    assert len(transactions) == 3
    assert all(item.operation_kind is OnlyExecutionOperationKind.TRADE_FILL for item in transactions)
    facts = tuple(item.fact for item in transactions)
    assert all(isinstance(item, OnlyCommittedExecutionFact) for item in facts)
    trade_facts = tuple(item for item in facts if isinstance(item, OnlyCommittedExecutionFact))
    assert tuple(item.fill_index for item in trade_facts) == (1, 2, 3)
    assert tuple(item.fill_quantity.value for item in trade_facts) == (Decimal("300"), Decimal("400"), Decimal("300"))
    assert tuple(item.position_quantity_after for item in trade_facts) == (
        Decimal("700"),
        Decimal("300"),
        Decimal("0"),
    )
    assert tuple(item.position_cumulative_open_price_quantity_after for item in trade_facts) == (
        Decimal("7000.00"),
        Decimal("3000.00"),
        Decimal("0"),
    )
    assert sum((item.released_open_price_quantity for item in trade_facts), Decimal(0)) == Decimal("10000.00")
    assert sum((item.realized_pnl_delta.amount for item in trade_facts), Decimal(0)) == Decimal("200.00")
    order = environment.runtime.order_manager.require_snapshot(first_context.update.order_id)
    assert order.status is OnlyOrderStatus.FILLED
    assert order.fill_count == 3
    assert order.remaining_quantity.value == 0
    position = next(
        item
        for item in environment.runtime.position_manager.closed()
        if item.position_id == first_context.position_before.position_id
    )
    assert position.status is OnlyPositionStatus.CLOSED
    assert position.cumulative_open_price_quantity == 0
    reservation = environment.runtime.position_reservation_manager.get(first_context.update.order_id)
    assert reservation is not None
    assert reservation.state is OnlyPositionReservationState.CONSUMED
    assert reservation.consumed_quantity is not None
    assert reservation.consumed_quantity.value == 1000
    assert reservation.remaining_quantity.value == 0
    risk_reservation = environment.runtime.risk_service.reservations.get_for_order(first_context.update.order_id)
    assert risk_reservation is not None
    assert risk_reservation.state is OnlyRiskReservationState.CONSUMED
    assert risk_reservation.consumed_quantity is not None
    assert risk_reservation.consumed_quantity.value == 1000
    assert risk_reservation.remaining_quantity.value == 0
    assert risk_reservation.remaining_notional is not None
    assert risk_reservation.remaining_notional.amount == 0
    risk = environment.runtime.risk_service.get_snapshot(first_context.order_before.cluster_id)
    assert risk.active_order_count == 0
    assert risk.cluster_active_order_count == 0


def test_long_close_fill_remains_durable_while_order_is_pending_cancel() -> None:
    environment, first_context, _ = only_test_generic_t0_long_close_context(
        open_quantity="1000",
        close_quantity="1000",
        fill_quantity="300",
    )
    processor = environment.runtime.execution_processor
    assert processor.process(first_context.update).status is OnlyExecutionProcessingStatus.APPLIED
    cancel_requested_at = first_context.update.ts_init
    mutation = environment.runtime.order_manager.request_cancel(first_context.update.order_id, cancel_requested_at)
    assert mutation.snapshot.status is OnlyOrderStatus.PENDING_CANCEL
    second_update = only_test_generic_t0_long_close_update(
        environment,
        first_context.update.order_id,
        suffix="pending-cancel-fill",
        fill_quantity="400",
        fill_price="11.00",
    )

    second = processor.process(second_update)

    assert second.status is OnlyExecutionProcessingStatus.APPLIED
    order = environment.runtime.order_manager.require_snapshot(first_context.update.order_id)
    assert order.status is OnlyOrderStatus.PENDING_CANCEL
    assert order.filled_quantity.value == 700
    records = environment.runtime.execution_transaction_query.transactions_for_order(
        first_context.update.runtime_id,
        first_context.update.order_id,
    )
    assert len(records) == 2
