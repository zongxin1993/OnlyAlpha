from copy import deepcopy
from datetime import date
from decimal import Decimal

import pytest
from conftest import ACCOUNT, bar
from onlyalpha_plugin_broker_virtual.fill_plan import OnlyVirtualFillScheduleStepSpec
from test_virtual_fill_schedule_matching import _accept, _gateway


def _partially_filled_gateway():  # type: ignore[no-untyped-def]
    steps = (
        OnlyVirtualFillScheduleStepSpec(1, quantity=Decimal("40")),
        OnlyVirtualFillScheduleStepSpec(2, quantity=Decimal("60")),
    )
    clock, gateway, _ = _gateway(steps=steps)
    _accept(clock, gateway)
    current = bar(date(2026, 1, 5), 1)
    clock.advance_to(current.ts_event)
    gateway.on_bar(current)
    return clock, gateway


def test_checkpoint_restores_plan_cursor_and_continues_only_remaining_step() -> None:
    clock, gateway = _partially_filled_gateway()
    gateway.restore_checkpoint(gateway.capture_checkpoint())
    current = bar(date(2026, 1, 5), 2)
    clock.advance_to(current.ts_event)
    gateway.on_bar(current)
    assert tuple(item.fill.quantity.value for item in gateway.query_trades(ACCOUNT)) == (
        Decimal("40"),
        Decimal("60"),
    )


def test_checkpoint_schema_and_plan_order_conflicts_fail_closed() -> None:
    _, gateway = _partially_filled_gateway()
    payload = gateway.capture_checkpoint()
    assert isinstance(payload, dict)
    old = deepcopy(payload)
    old["schema_version"] = 1
    with pytest.raises(ValueError, match="SCHEMA_UNSUPPORTED"):
        gateway.restore_checkpoint(old)
    corrupt = deepcopy(payload)
    assert isinstance(corrupt["fill_plans"], list) and isinstance(corrupt["fill_plans"][0], dict)
    corrupt["fill_plans"][0]["next_step_index"] = 0
    with pytest.raises(ValueError, match="AUTHORITY_CONFLICT"):
        gateway.restore_checkpoint(corrupt)
