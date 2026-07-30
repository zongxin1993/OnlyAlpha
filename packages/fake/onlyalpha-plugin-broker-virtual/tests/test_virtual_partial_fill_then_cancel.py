from datetime import date
from decimal import Decimal

from conftest import ACCOUNT, bar, order
from onlyalpha_plugin_broker_virtual.fill_plan import OnlyVirtualFillPlanStatus, OnlyVirtualFillScheduleStepSpec
from test_virtual_fill_schedule_matching import _accept, _gateway

from onlyalpha.broker import OnlyBrokerCancelRequest, OnlyBrokerRequestId
from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.time import OnlyTimestamp


def test_partial_fill_then_cancel_terminates_remaining_plan_steps() -> None:
    steps = (
        OnlyVirtualFillScheduleStepSpec(1, quantity=Decimal("40")),
        OnlyVirtualFillScheduleStepSpec(2, quantity=Decimal("60")),
    )
    clock, gateway, _ = _gateway(steps=steps)
    _accept(clock, gateway)
    current = bar(date(2026, 1, 5), 1)
    clock.advance_to(current.ts_event)
    gateway.on_bar(current)
    request = order(1)
    gateway.cancel_order(
        OnlyBrokerCancelRequest(
            OnlyBrokerRequestId("cancel"),
            ACCOUNT,
            request.order_id,
            None,
            OnlyTimestamp.from_datetime(current.ts_event),
        )
    )
    gateway.run_due()
    future = bar(date(2026, 1, 5), 2)
    clock.advance_to(future.ts_event)
    gateway.on_bar(future)
    assert gateway.query_orders(ACCOUNT)[0].status is OnlyOrderStatus.CANCELLED
    assert gateway.fill_plan_store.list()[0].status is OnlyVirtualFillPlanStatus.CANCELLED
    assert len(gateway.query_trades(ACCOUNT)) == 1
    assert gateway.query_account(ACCOUNT).frozen_cash.amount == Decimal("0.00")
