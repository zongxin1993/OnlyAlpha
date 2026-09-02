from dataclasses import replace
from decimal import Decimal

import pytest
from onlyalpha_plugin_broker_virtual.fill_plan import (
    OnlyVirtualFillDispatchMode,
    OnlyVirtualFillPlanStatus,
    OnlyVirtualFillScheduleMode,
    only_create_virtual_order_fill_plan,
)
from onlyalpha_plugin_broker_virtual.fill_plan_store import OnlyVirtualFillPlanStore

from onlyalpha.domain.identifiers import OnlyAccountId, OnlyOrderId, OnlyVenueOrderId
from onlyalpha.domain.value import OnlyQuantity


def _plan(order_id: str = "order"):
    return only_create_virtual_order_fill_plan(
        gateway_id="virtual",
        account_id=OnlyAccountId("account"),
        order_id=OnlyOrderId(order_id),
        venue_order_id=OnlyVenueOrderId(f"venue-{order_id}"),
        original_quantity=OnlyQuantity(Decimal("10"), 0),
        accepted_bar_sequence=0,
        mode=OnlyVirtualFillScheduleMode.MAX_PER_BAR,
        dispatch_mode=OnlyVirtualFillDispatchMode.ONE_PER_BAR,
        maximum_fill_quantity=OnlyQuantity(Decimal("4"), 0),
    )


def test_store_advances_versions_completes_and_round_trips_in_stable_order() -> None:
    store = OnlyVirtualFillPlanStore()
    store.save(_plan("b"))
    store.save(_plan("a"))
    first = store.advance(OnlyOrderId("a"))
    assert first.next_step_index == 1 and first.version == 2
    store.advance(OnlyOrderId("a"))
    completed = store.advance(OnlyOrderId("a"))
    assert completed.status is OnlyVirtualFillPlanStatus.COMPLETED
    restored = OnlyVirtualFillPlanStore()
    restored.restore_checkpoint(store.capture_checkpoint())
    assert restored.list() == store.list()
    assert tuple(str(item.order_id) for item in restored.list()) == ("a", "b")
    with pytest.raises(ValueError, match="TERMINAL_ADVANCE"):
        restored.advance(OnlyOrderId("a"))


def test_store_rejects_duplicate_cancelled_and_corrupt_payload() -> None:
    store = OnlyVirtualFillPlanStore()
    plan = _plan()
    store.save(plan)
    with pytest.raises(ValueError, match="DUPLICATE_ORDER"):
        store.save(plan)
    cancelled = store.cancel(plan.order_id)
    assert cancelled.status is OnlyVirtualFillPlanStatus.CANCELLED and cancelled.version == 2
    payload = store.capture_checkpoint()
    assert isinstance(payload, list) and isinstance(payload[0], dict)
    payload[0]["next_step_index"] = 99
    with pytest.raises(ValueError, match="CURSOR_INVALID"):
        OnlyVirtualFillPlanStore().restore_checkpoint(payload)


def test_store_rejects_snapshot_with_invalid_terminal_state() -> None:
    store = OnlyVirtualFillPlanStore()
    with pytest.raises(ValueError, match="COMPLETED_CURSOR_INVALID"):
        store.save(replace(_plan(), status=OnlyVirtualFillPlanStatus.COMPLETED))
