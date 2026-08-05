from dataclasses import replace

import pytest

from onlyalpha.broker.identifiers import OnlyBrokerUpdateId
from onlyalpha.broker.updates import (
    OnlyBrokerOrderCancelledUpdate,
    OnlyBrokerOrderExpiredUpdate,
    OnlyBrokerOrderRejectedUpdate,
)
from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.execution import OnlyOrderRejection
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.execution.enums import OnlyExecutionProcessingStatus
from onlyalpha.execution.terminal_fact import OnlyCommittedTerminalExecutionFact
from onlyalpha.execution.terminal_identity import only_capture_execution_terminal_authority
from onlyalpha.position.enums import OnlyPositionReservationState, OnlyPositionStatus
from onlyalpha.risk.enums import OnlyRiskReservationState
from onlyalpha.transaction.enums import OnlyRuntimeOperationKind
from onlyalpha.transaction.projection import OnlyRuntimeProjectionComponent
from tests.execution.support.generic_t0_trade_harness import only_test_generic_t0_long_close_context


def _terminal_update(
    terminal: str,
) -> tuple[
    object, object, OnlyBrokerOrderCancelledUpdate | OnlyBrokerOrderRejectedUpdate | OnlyBrokerOrderExpiredUpdate
]:
    environment, context, _ = only_test_generic_t0_long_close_context(
        open_quantity="1000",
        close_quantity="1000",
        fill_quantity="300",
    )
    fill_result = environment.runtime.execution_processor.process(context.update)
    assert fill_result.status is OnlyExecutionProcessingStatus.APPLIED
    order = environment.runtime.order_manager.require_snapshot(context.update.order_id)
    ts_event = OnlyTimestamp.from_unix_nanos(environment.runtime.clock.timestamp_ns())
    environment.runtime.clock.advance_by(1_000_000_000)
    common = {
        "runtime_id": context.update.runtime_id,
        "gateway_id": context.update.gateway_id,
        "account_id": context.update.account_id,
        "update_id": OnlyBrokerUpdateId(f"terminal-{terminal.lower()}"),
        "source_sequence": (order.last_external_sequence or 0) + 1,
        "ts_event": ts_event,
        "ts_init": OnlyTimestamp.from_unix_nanos(environment.runtime.clock.timestamp_ns()),
        "correlation_id": str(order.order_id),
        "causation_id": "partial-close-terminal",
        "order_id": order.order_id,
    }
    if terminal == "REJECTED":
        update = OnlyBrokerOrderRejectedUpdate(
            **common,
            rejection=OnlyOrderRejection("VENUE_REJECT", "remaining quantity rejected"),
        )
    elif terminal == "EXPIRED":
        update = OnlyBrokerOrderExpiredUpdate(**common)
    else:
        update = OnlyBrokerOrderCancelledUpdate(**common)
    return environment, context, update


@pytest.mark.parametrize(
    ("terminal", "expected"),
    [
        ("CANCELLED", OnlyOrderStatus.CANCELLED),
        ("REJECTED", OnlyOrderStatus.REJECTED),
        ("EXPIRED", OnlyOrderStatus.EXPIRED),
    ],
)
def test_partial_long_close_terminal_is_one_durable_transaction(
    terminal: str,
    expected: OnlyOrderStatus,
) -> None:
    environment, context, update = _terminal_update(terminal)

    result = environment.runtime.execution_processor.process(update)

    assert result.status is OnlyExecutionProcessingStatus.APPLIED, (
        None if result.failure is None else result.failure.message
    )
    transactions = environment.runtime.execution_transaction_query.transactions_for_order(
        update.runtime_id,
        update.order_id,
    )
    assert len(transactions) == 2
    committed = transactions[-1]
    assert committed.operation_kind is OnlyRuntimeOperationKind.ORDER_TERMINAL
    assert not hasattr(committed.fact, "trade_id")
    assert isinstance(committed.fact, OnlyCommittedTerminalExecutionFact)
    assert tuple(item.identity.component for item in committed.projections) == (
        OnlyRuntimeProjectionComponent.ORDER,
        OnlyRuntimeProjectionComponent.POSITION_RESERVATION,
        OnlyRuntimeProjectionComponent.RISK_RESERVATION,
        OnlyRuntimeProjectionComponent.RISK,
    )
    order = environment.runtime.order_manager.require_snapshot(update.order_id)
    assert order.status is expected
    assert order.filled_quantity.value == 300
    assert order.remaining_quantity.value == 700
    position = environment.runtime.position_manager.require_snapshot(context.position_scope.position_key)
    assert position.status is OnlyPositionStatus.OPEN
    assert position.total_quantity.value == 700
    position_reservation = environment.runtime.position_reservation_manager.get(update.order_id)
    assert position_reservation is not None
    assert position_reservation.consumed_quantity is not None
    assert position_reservation.released_quantity is not None
    assert position_reservation.consumed_quantity.value == 300
    assert position_reservation.released_quantity.value == 700
    assert position_reservation.remaining_quantity.value == 0
    assert position_reservation.state is OnlyPositionReservationState.RELEASED
    risk_reservation = environment.runtime.risk_service.reservations.get_for_order(update.order_id)
    assert risk_reservation is not None
    assert risk_reservation.consumed_quantity is not None
    assert risk_reservation.released_quantity is not None
    assert risk_reservation.consumed_quantity.value == 300
    assert risk_reservation.released_quantity.value == 700
    assert risk_reservation.remaining_quantity.value == 0
    assert risk_reservation.state is OnlyRiskReservationState.RELEASED


def test_terminal_identity_duplicate_and_payload_conflict_are_fail_closed() -> None:
    environment, _, update = _terminal_update("CANCELLED")
    authority = only_capture_execution_terminal_authority(update)

    first = environment.runtime.execution_processor.process(update)
    duplicate = environment.runtime.execution_processor.process(update)
    conflict_update = replace(update, metadata={"reason": "different-payload"})
    conflict_authority = only_capture_execution_terminal_authority(conflict_update)
    conflict = environment.runtime.execution_processor.process(conflict_update)

    assert first.status is OnlyExecutionProcessingStatus.APPLIED
    assert duplicate.status is OnlyExecutionProcessingStatus.DUPLICATE
    assert conflict_authority.terminal_identity == authority.terminal_identity
    assert conflict_authority.payload_fingerprint != authority.payload_fingerprint
    assert conflict.status is OnlyExecutionProcessingStatus.REJECTED
    assert conflict.failure is not None
    assert "TERMINAL_IDENTITY_CONFLICT" in conflict.failure.message
