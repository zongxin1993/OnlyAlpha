from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.identifiers import OnlyVenueOrderId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.order.enums import OnlyOrderApplyResult
from onlyalpha.order.manager import OnlyOrderManager

from .conftest import only_fill


def test_duplicate_request_and_fill_are_idempotent(
    order_manager: OnlyOrderManager, order_request, created_order
) -> None:
    duplicate_create = order_manager.create_order(
        order_request,
        created_order.snapshot.cluster_id,
        created_order.snapshot.account_id,
        OnlyTimestamp.from_unix_nanos(2),
    )
    assert duplicate_create.order_id == created_order.order_id
    assert duplicate_create.apply_result is OnlyOrderApplyResult.DUPLICATE
    order_manager.mark_submitted(created_order.order_id, OnlyTimestamp.from_unix_nanos(2))
    fill = only_fill(created_order.order_id, "trade-1", "1", "10.00", 3)
    first = order_manager.apply_fill(fill)
    duplicate = order_manager.apply_fill(fill)
    assert first.changed
    assert duplicate.apply_result is OnlyOrderApplyResult.DUPLICATE
    assert duplicate.snapshot.filled_quantity == first.snapshot.filled_quantity
    assert duplicate.events == ()


def test_fill_before_accepted_and_late_accepted_do_not_roll_back(
    order_manager: OnlyOrderManager, created_order
) -> None:
    order_id = created_order.order_id
    order_manager.mark_submitted(order_id, OnlyTimestamp.from_unix_nanos(2))
    partial = order_manager.apply_fill(only_fill(order_id, "trade-1", "1", "10.00", 5))
    late = order_manager.apply_accepted(
        order_id,
        OnlyTimestamp.from_unix_nanos(3),
        OnlyVenueOrderId("venue-1"),
        event_time=OnlyTimestamp.from_unix_nanos(3),
    )
    assert partial.current_status is OnlyOrderStatus.PARTIALLY_FILLED
    assert late.current_status is OnlyOrderStatus.PARTIALLY_FILLED
    assert late.snapshot.venue_order_id == OnlyVenueOrderId("venue-1")
    assert late.snapshot.updated_at.unix_nanos == 5


def test_external_sequence_rejects_stale_update(order_manager: OnlyOrderManager, created_order) -> None:
    order_id = created_order.order_id
    order_manager.mark_submitted(order_id, OnlyTimestamp.from_unix_nanos(2))
    order_manager.apply_accepted(
        order_id,
        OnlyTimestamp.from_unix_nanos(3),
        OnlyVenueOrderId("venue-1"),
        external_sequence=10,
        external_event_id="accepted-10",
    )
    stale = order_manager.apply_cancelled(
        order_id,
        OnlyTimestamp.from_unix_nanos(4),
        external_sequence=9,
        external_event_id="cancelled-9",
    )
    assert stale.apply_result is OnlyOrderApplyResult.STALE
    assert stale.current_status is OnlyOrderStatus.ACCEPTED
    assert stale.events == ()


def test_late_fill_after_cancel_is_recorded_without_reopening(order_manager: OnlyOrderManager, created_order) -> None:
    order_id = created_order.order_id
    order_manager.mark_submitted(order_id, OnlyTimestamp.from_unix_nanos(2))
    order_manager.apply_cancelled(order_id, OnlyTimestamp.from_unix_nanos(3))
    late = order_manager.apply_fill(only_fill(order_id, "late-trade", "1", "10.00", 4))
    assert late.current_status is OnlyOrderStatus.CANCELLED
    assert late.snapshot.filled_quantity.value == 1
    assert "late Fill" in late.warnings[0]
