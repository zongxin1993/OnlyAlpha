from decimal import Decimal

import pytest

from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.trading import (
    OnlyExposureConstraint,
    OnlyPositionEffect,
    OnlyPositionMode,
    OnlyPositionSide,
    OnlyTargetExposure,
)
from onlyalpha.execution.intent_planner import (
    OnlyExposureState,
    only_plan_hedged_target_exposure,
    only_plan_target_exposure,
)
from onlyalpha.market.models import OnlyShortSellingMode
from onlyalpha.position.enums import OnlyPositionFlipPolicy


def _plan(current: OnlyExposureState, target: OnlyTargetExposure, quantity: str, **changes: object):
    arguments = {
        "current": current,
        "target": target,
        "target_quantity": Decimal(quantity),
        "position_mode": OnlyPositionMode.NETTING,
        "short_mode": OnlyShortSellingMode.ENABLED_UNRESTRICTED,
        "flip_policy": OnlyPositionFlipPolicy.CLOSE_THEN_OPEN,
    }
    arguments.update(changes)
    return only_plan_target_exposure(**arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("target", "side", "position_side"),
    (
        (OnlyTargetExposure.LONG, OnlyOrderSide.BUY, OnlyPositionSide.LONG),
        (OnlyTargetExposure.SHORT, OnlyOrderSide.SELL, OnlyPositionSide.SHORT),
    ),
)
def test_flat_target_compiles_without_provider_interpretation(
    target: OnlyTargetExposure, side: OnlyOrderSide, position_side: OnlyPositionSide
) -> None:
    (leg,) = _plan(OnlyExposureState(), target, "3")
    assert (leg.intent.side, leg.intent.position_side, leg.intent.position_effect, leg.quantity) == (
        side,
        position_side,
        OnlyPositionEffect.OPEN,
        Decimal("3"),
    )


def test_spot_short_target_fails_closed() -> None:
    with pytest.raises(ValueError, match="TARGET_SHORT_DISABLED"):
        _plan(
            OnlyExposureState(),
            OnlyTargetExposure.SHORT,
            "1",
            short_mode=OnlyShortSellingMode.DISABLED,
        )


def test_netting_flip_is_explicit_close_then_open() -> None:
    close, opening = _plan(OnlyExposureState(long_quantity=Decimal("2")), OnlyTargetExposure.SHORT, "3")
    assert (close.intent.side, close.intent.position_side, close.intent.position_effect, close.quantity) == (
        OnlyOrderSide.SELL,
        OnlyPositionSide.LONG,
        OnlyPositionEffect.CLOSE,
        Decimal("2"),
    )
    assert close.intent.exposure_constraint is OnlyExposureConstraint.REDUCE_ONLY
    assert (opening.intent.side, opening.intent.position_side, opening.intent.position_effect, opening.quantity) == (
        OnlyOrderSide.SELL,
        OnlyPositionSide.SHORT,
        OnlyPositionEffect.OPEN,
        Decimal("3"),
    )


def test_flip_reject_policy_never_implicitly_crosses_zero() -> None:
    with pytest.raises(ValueError, match="POSITION_FLIP_POLICY_REJECTED"):
        _plan(
            OnlyExposureState(short_quantity=Decimal("2")),
            OnlyTargetExposure.LONG,
            "1",
            flip_policy=OnlyPositionFlipPolicy.REJECT,
        )


def test_hedging_rebalances_named_legs_independently() -> None:
    close, opening = only_plan_hedged_target_exposure(
        current=OnlyExposureState(long_quantity=Decimal("1"), short_quantity=Decimal("2")),
        target_long_quantity=Decimal("4"),
        target_short_quantity=Decimal("1"),
        short_mode=OnlyShortSellingMode.ENABLED_UNRESTRICTED,
    )
    assert (close.intent.position_side, close.intent.side, close.quantity) == (
        OnlyPositionSide.SHORT,
        OnlyOrderSide.BUY,
        Decimal("1"),
    )
    assert (opening.intent.position_side, opening.intent.side, opening.quantity) == (
        OnlyPositionSide.LONG,
        OnlyOrderSide.BUY,
        Decimal("3"),
    )


def test_net_target_api_rejects_hedging_ambiguity() -> None:
    with pytest.raises(ValueError, match="HEDGING_REQUIRES_PER_LEG_TARGETS"):
        _plan(
            OnlyExposureState(),
            OnlyTargetExposure.LONG,
            "1",
            position_mode=OnlyPositionMode.HEDGING,
        )
