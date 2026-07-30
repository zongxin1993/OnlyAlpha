from datetime import date
from decimal import Decimal

from conftest import ACCOUNT, bar
from onlyalpha_plugin_broker_virtual.fill_plan import (
    OnlyVirtualFillDispatchMode,
    OnlyVirtualFillScheduleStepSpec,
)
from test_virtual_fill_schedule_matching import _accept, _gateway


def test_all_due_executes_two_independent_fills_on_same_bar() -> None:
    steps = (
        OnlyVirtualFillScheduleStepSpec(1, quantity=Decimal("30")),
        OnlyVirtualFillScheduleStepSpec(1, quantity=Decimal("40")),
        OnlyVirtualFillScheduleStepSpec(2, quantity=Decimal("30")),
    )
    clock, gateway, updates = _gateway(steps=steps, dispatch=OnlyVirtualFillDispatchMode.ALL_DUE)
    _accept(clock, gateway)
    current = bar(date(2026, 1, 5), 1)
    clock.advance_to(current.ts_event)
    gateway.on_bar(current)
    trades = gateway.query_trades(ACCOUNT)
    assert tuple(item.fill.quantity.value for item in trades) == (Decimal("30"), Decimal("40"))
    assert trades[0].trade_id != trades[1].trade_id
    assert trades[0].source_sequence + 1 == trades[1].source_sequence
    fill_updates = tuple(item for item in updates if type(item).__name__ == "OnlyBrokerTradeUpdate")
    assert len(fill_updates) == 2 and fill_updates[0].update_id != fill_updates[1].update_id
