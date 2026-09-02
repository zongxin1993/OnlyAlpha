from decimal import Decimal

import pytest
from onlyalpha_plugin_broker_virtual.fill_plan import (
    OnlyVirtualFillDispatchMode,
    OnlyVirtualFillScheduleMode,
    OnlyVirtualFillScheduleStepSpec,
    only_create_virtual_order_fill_plan,
    only_virtual_fill_plan_from_checkpoint,
    only_virtual_fill_plan_to_checkpoint,
)

from onlyalpha.domain.identifiers import OnlyAccountId, OnlyOrderId, OnlyVenueOrderId
from onlyalpha.domain.value import OnlyQuantity


def _plan(
    quantity: str,
    specs: tuple[OnlyVirtualFillScheduleStepSpec, ...],
    *,
    precision: int = 0,
    mode: OnlyVirtualFillScheduleMode = OnlyVirtualFillScheduleMode.SCHEDULE,
    maximum: str | None = None,
):
    return only_create_virtual_order_fill_plan(
        gateway_id="virtual",
        account_id=OnlyAccountId("account"),
        order_id=OnlyOrderId("order"),
        venue_order_id=OnlyVenueOrderId("venue-order"),
        original_quantity=OnlyQuantity(Decimal(quantity), precision),
        accepted_bar_sequence=4,
        mode=mode,
        dispatch_mode=OnlyVirtualFillDispatchMode.ONE_PER_BAR,
        schedule_steps=specs,
        maximum_fill_quantity=None if maximum is None else OnlyQuantity(Decimal(maximum), precision),
    )


def test_quantity_and_ratio_normalization_conserve_exact_quantity() -> None:
    quantity = _plan(
        "1000",
        tuple(
            OnlyVirtualFillScheduleStepSpec(index, quantity=value)
            for index, value in enumerate((Decimal("300"), Decimal("400"), Decimal("300")), start=1)
        ),
    )
    ratio = _plan(
        "101",
        tuple(
            OnlyVirtualFillScheduleStepSpec(index, ratio=value)
            for index, value in enumerate((Decimal("0.30"), Decimal("0.40"), Decimal("0.30")), start=1)
        ),
    )
    assert tuple(step.quantity.value for step in quantity.steps) == (Decimal("300"), Decimal("400"), Decimal("300"))
    assert tuple(step.quantity.value for step in ratio.steps) == (Decimal("30"), Decimal("40"), Decimal("31"))
    assert sum((step.quantity.value for step in ratio.steps), Decimal(0)) == Decimal("101")


def test_whole_and_max_per_bar_share_normalized_plan_execution() -> None:
    whole = _plan("1000", (), mode=OnlyVirtualFillScheduleMode.WHOLE)
    maximum = _plan("1000", (), mode=OnlyVirtualFillScheduleMode.MAX_PER_BAR, maximum="300")
    assert tuple(step.quantity.value for step in whole.steps) == (Decimal("1000"),)
    assert tuple(step.quantity.value for step in maximum.steps) == (
        Decimal("300"),
        Decimal("300"),
        Decimal("300"),
        Decimal("100"),
    )


def test_plan_identity_is_stable_and_checkpoint_round_trips() -> None:
    specs = (
        OnlyVirtualFillScheduleStepSpec(1, ratio=Decimal("0.3")),
        OnlyVirtualFillScheduleStepSpec(2, ratio=Decimal("0.7")),
    )
    first = _plan("10.0", specs, precision=1)
    second = _plan("10.0", specs, precision=1)
    restored = only_virtual_fill_plan_from_checkpoint(only_virtual_fill_plan_to_checkpoint(first))
    assert first.plan_id == second.plan_id == f"VPLAN-{first.plan_fingerprint}"
    assert restored == first


@pytest.mark.parametrize(
    "specs, code",
    [
        (
            (
                OnlyVirtualFillScheduleStepSpec(1, quantity=Decimal("4")),
                OnlyVirtualFillScheduleStepSpec(2, quantity=Decimal("5")),
            ),
            "VIRTUAL_FILL_PLAN_QUANTITY_MISMATCH",
        ),
        (
            (
                OnlyVirtualFillScheduleStepSpec(1, ratio=Decimal("0.4")),
                OnlyVirtualFillScheduleStepSpec(2, ratio=Decimal("0.5")),
            ),
            "VIRTUAL_FILL_SCHEDULE_RATIO_SUM_INVALID",
        ),
    ],
)
def test_overfill_or_underfill_is_rejected(specs, code: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError, match=code):
        _plan("10", specs)
