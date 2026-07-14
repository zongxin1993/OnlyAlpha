from decimal import Decimal

from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.execution import OnlyOrderFailure, OnlyOrderRejection
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyOrderRequestId, OnlyVenueOrderId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.order.enums import OnlyOrderApplyResult
from onlyalpha.order.manager import OnlyOrderManager

from .conftest import only_fill


def test_complete_fill_state_machine(order_manager: OnlyOrderManager, created_order) -> None:
    order_id = created_order.order_id
    submitted = order_manager.mark_submitted(order_id, OnlyTimestamp.from_unix_nanos(2))
    accepted = order_manager.apply_accepted(order_id, OnlyTimestamp.from_unix_nanos(3), OnlyVenueOrderId("venue-1"))
    partial = order_manager.apply_fill(only_fill(order_id, "trade-1", "1", "10.00", 4))
    filled = order_manager.apply_fill(only_fill(order_id, "trade-2", "3", "14.00", 5))
    assert [item.current_status for item in (submitted, accepted, partial, filled)] == [
        OnlyOrderStatus.SUBMITTED,
        OnlyOrderStatus.ACCEPTED,
        OnlyOrderStatus.PARTIALLY_FILLED,
        OnlyOrderStatus.FILLED,
    ]
    assert filled.snapshot.average_fill_price is not None
    assert filled.snapshot.average_fill_price.value == Decimal("13.00")
    assert filled.snapshot.remaining_quantity.value == 0


def test_invalid_overfill_and_terminal_transition_publish_no_event(
    order_manager: OnlyOrderManager, created_order
) -> None:
    order_id = created_order.order_id
    order_manager.mark_submitted(order_id, OnlyTimestamp.from_unix_nanos(2))
    invalid = order_manager.apply_fill(only_fill(order_id, "trade-over", "5", "10.00", 3))
    assert invalid.apply_result is OnlyOrderApplyResult.INVALID
    assert not invalid.changed and invalid.events == ()
    rejected = order_manager.apply_rejected(
        order_id,
        OnlyTimestamp.from_unix_nanos(4),
        OnlyOrderRejection("VENUE_REJECT", "rejected"),
    )
    assert rejected.current_status is OnlyOrderStatus.REJECTED
    failed = order_manager.apply_failed(
        order_id,
        OnlyTimestamp.from_unix_nanos(5),
        OnlyOrderFailure("TRANSPORT", "late failure"),
    )
    assert failed.apply_result is OnlyOrderApplyResult.INVALID
    assert failed.events == ()


def test_cancel_after_partial_fill_retains_fill_history(order_manager: OnlyOrderManager, created_order) -> None:
    order_id = created_order.order_id
    order_manager.mark_submitted(order_id, OnlyTimestamp.from_unix_nanos(2))
    order_manager.apply_accepted(order_id, OnlyTimestamp.from_unix_nanos(3), OnlyVenueOrderId("venue-1"))
    order_manager.apply_fill(only_fill(order_id, "trade-1", "1", "10.00", 4))
    pending = order_manager.request_cancel(order_id, OnlyTimestamp.from_unix_nanos(5))
    cancelled = order_manager.apply_cancelled(order_id, OnlyTimestamp.from_unix_nanos(6))
    assert pending.current_status is OnlyOrderStatus.PENDING_CANCEL
    assert cancelled.current_status is OnlyOrderStatus.CANCELLED
    assert cancelled.snapshot.filled_quantity.value == 1
    assert cancelled.snapshot.remaining_quantity.value == 0


def test_expired_and_failed_are_explicit_terminal_states(
    order_manager: OnlyOrderManager, order_request, created_order
) -> None:
    order_id = created_order.order_id
    order_manager.mark_submitted(order_id, OnlyTimestamp.from_unix_nanos(2))
    order_manager.apply_accepted(order_id, OnlyTimestamp.from_unix_nanos(3), OnlyVenueOrderId("venue-1"))
    expired = order_manager.apply_expired(order_id, OnlyTimestamp.from_unix_nanos(4))
    assert expired.current_status is OnlyOrderStatus.EXPIRED

    from dataclasses import replace

    second = order_manager.create_order(
        replace(order_request, request_id=OnlyOrderRequestId("request-2")),
        OnlyClusterId("cluster-a"),
        OnlyAccountId("account"),
        OnlyTimestamp.from_unix_nanos(5),
    )
    failed = order_manager.apply_failed(
        second.order_id,
        OnlyTimestamp.from_unix_nanos(6),
        OnlyOrderFailure("LOCAL_FAILURE", "explicit failure"),
    )
    assert failed.current_status is OnlyOrderStatus.FAILED
