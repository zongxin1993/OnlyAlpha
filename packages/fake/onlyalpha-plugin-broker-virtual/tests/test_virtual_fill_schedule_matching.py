from dataclasses import replace
from datetime import date
from decimal import Decimal

from onlyalpha_plugin_broker_virtual import OnlyVirtualBrokerConfig, OnlyVirtualBrokerGateway
from onlyalpha_plugin_broker_virtual.fill_plan import (
    OnlyVirtualFillDispatchMode,
    OnlyVirtualFillPlanStatus,
    OnlyVirtualFillScheduleMode,
    OnlyVirtualFillScheduleStepSpec,
)

from onlyalpha.broker import OnlyBrokerGatewayId
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.value import OnlyMoney, OnlyPrice
from tests.support.virtual_broker import ACCOUNT, CNY, START, bar, order


def _gateway(*, steps, dispatch=OnlyVirtualFillDispatchMode.ONE_PER_BAR):  # type: ignore[no-untyped-def]
    clock = OnlyBacktestClock(START)
    updates = []
    gateway = OnlyVirtualBrokerGateway(
        OnlyVirtualBrokerConfig(
            OnlyBrokerGatewayId("schedule"),
            ACCOUNT,
            CNY,
            OnlyMoney(Decimal("100000.00"), CNY),
            fill_schedule_mode=OnlyVirtualFillScheduleMode.SCHEDULE,
            fill_dispatch_mode=dispatch,
            fill_schedule_steps=steps,
        ),
        OnlyRuntimeId("schedule-runtime"),
        clock,
        updates.append,
    )
    gateway.connect()
    gateway.authenticate()
    return clock, gateway, updates


def _accept(clock, gateway):  # type: ignore[no-untyped-def]
    first = bar(date(2026, 1, 5), 0)
    clock.advance_to(first.ts_event)
    gateway.on_bar(first)
    gateway.submit_order(order(1))
    gateway.run_due()


def test_cross_bar_schedule_executes_30_40_30_and_completes() -> None:
    steps = tuple(
        OnlyVirtualFillScheduleStepSpec(index, quantity=value)
        for index, value in enumerate((Decimal("30"), Decimal("40"), Decimal("30")), start=1)
    )
    clock, gateway, _ = _gateway(steps=steps)
    _accept(clock, gateway)
    for minute in range(1, 4):
        current = bar(date(2026, 1, 5), minute)
        clock.advance_to(current.ts_event)
        gateway.on_bar(current)
    assert tuple(item.fill.quantity.value for item in gateway.query_trades(ACCOUNT)) == (
        Decimal("30"),
        Decimal("40"),
        Decimal("30"),
    )
    assert gateway.query_orders(ACCOUNT)[0].status is OnlyOrderStatus.FILLED
    assert gateway.fill_plan_store.list()[0].status is OnlyVirtualFillPlanStatus.COMPLETED


def test_due_step_waits_until_price_crosses() -> None:
    steps = (OnlyVirtualFillScheduleStepSpec(1, quantity=Decimal("100")),)
    clock, gateway, _ = _gateway(steps=steps)
    first = bar(date(2026, 1, 5), 0)
    clock.advance_to(first.ts_event)
    gateway.on_bar(first)
    gateway.submit_order(replace(order(1), price=OnlyPrice(Decimal("9.80"), 2)))
    gateway.run_due()
    missed = bar(date(2026, 1, 5), 1)
    clock.advance_to(missed.ts_event)
    gateway.on_bar(missed)
    assert gateway.query_trades(ACCOUNT) == ()
    crossed = bar(date(2026, 1, 5), 2, low="9.70")
    clock.advance_to(crossed.ts_event)
    gateway.on_bar(crossed)
    assert len(gateway.query_trades(ACCOUNT)) == 1
