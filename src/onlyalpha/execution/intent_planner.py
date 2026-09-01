"""Deterministic target-exposure to canonical execution-intent planning."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.trading import (
    OnlyExecutionIntent,
    OnlyExposureConstraint,
    OnlyPositionEffect,
    OnlyPositionMode,
    OnlyPositionSide,
    OnlyTargetExposure,
)
from onlyalpha.market.models import OnlyShortSellingMode
from onlyalpha.position.enums import OnlyPositionFlipPolicy


@dataclass(frozen=True, slots=True)
class OnlyExposureState:
    """Current canonical leg quantities; quantities are always unsigned."""

    long_quantity: Decimal = Decimal(0)
    short_quantity: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        if self.long_quantity < 0 or self.short_quantity < 0:
            raise ValueError("EXPOSURE_STATE_QUANTITY_NEGATIVE")


@dataclass(frozen=True, slots=True)
class OnlyPlannedExecutionIntent:
    intent: OnlyExecutionIntent
    quantity: Decimal

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("PLANNED_EXECUTION_QUANTITY_NOT_POSITIVE")


def only_plan_target_exposure(
    *,
    current: OnlyExposureState,
    target: OnlyTargetExposure,
    target_quantity: Decimal,
    position_mode: OnlyPositionMode,
    short_mode: OnlyShortSellingMode,
    flip_policy: OnlyPositionFlipPolicy,
) -> tuple[OnlyPlannedExecutionIntent, ...]:
    """Compile economic exposure into ordered, provider-neutral execution legs."""

    if target_quantity < 0 or (target is OnlyTargetExposure.FLAT) != (target_quantity == 0):
        raise ValueError("TARGET_EXPOSURE_QUANTITY_CONFLICT")
    if position_mode is OnlyPositionMode.HEDGING:
        raise ValueError("HEDGING_REQUIRES_PER_LEG_TARGETS")
    if position_mode is OnlyPositionMode.NETTING and current.long_quantity and current.short_quantity:
        raise ValueError("NETTING_EXPOSURE_HAS_TWO_LEGS")
    if target is OnlyTargetExposure.SHORT and short_mode is OnlyShortSellingMode.DISABLED:
        raise ValueError("TARGET_SHORT_DISABLED")

    desired_long = target_quantity if target is OnlyTargetExposure.LONG else Decimal(0)
    desired_short = target_quantity if target is OnlyTargetExposure.SHORT else Decimal(0)
    crosses_side = (current.long_quantity and desired_short) or (current.short_quantity and desired_long)
    if crosses_side and flip_policy is not OnlyPositionFlipPolicy.CLOSE_THEN_OPEN:
        raise ValueError("POSITION_FLIP_POLICY_REJECTED")

    result: list[OnlyPlannedExecutionIntent] = []
    _append_delta(result, OnlyPositionSide.LONG, current.long_quantity, desired_long)
    _append_delta(result, OnlyPositionSide.SHORT, current.short_quantity, desired_short)
    # All reductions are deliberately ordered before increases.  This keeps a
    # flip explicit and prevents a provider from interpreting one ambiguous SELL.
    return tuple(sorted(result, key=lambda item: item.intent.position_effect is OnlyPositionEffect.OPEN))


def only_plan_hedged_target_exposure(
    *,
    current: OnlyExposureState,
    target_long_quantity: Decimal,
    target_short_quantity: Decimal,
    short_mode: OnlyShortSellingMode,
) -> tuple[OnlyPlannedExecutionIntent, ...]:
    """Plan independent long/short leg targets without imposing net semantics."""

    if min(target_long_quantity, target_short_quantity) < 0:
        raise ValueError("HEDGED_TARGET_QUANTITY_NEGATIVE")
    if target_short_quantity and short_mode is OnlyShortSellingMode.DISABLED:
        raise ValueError("TARGET_SHORT_DISABLED")
    result: list[OnlyPlannedExecutionIntent] = []
    _append_delta(result, OnlyPositionSide.LONG, current.long_quantity, target_long_quantity)
    _append_delta(result, OnlyPositionSide.SHORT, current.short_quantity, target_short_quantity)
    return tuple(sorted(result, key=lambda item: item.intent.position_effect is OnlyPositionEffect.OPEN))


def _append_delta(
    result: list[OnlyPlannedExecutionIntent],
    side: OnlyPositionSide,
    current: Decimal,
    desired: Decimal,
) -> None:
    if current == desired:
        return
    effect = OnlyPositionEffect.OPEN if desired > current else OnlyPositionEffect.CLOSE
    order_side = (
        OnlyOrderSide.BUY
        if (side, effect)
        in {
            (OnlyPositionSide.LONG, OnlyPositionEffect.OPEN),
            (OnlyPositionSide.SHORT, OnlyPositionEffect.CLOSE),
        }
        else OnlyOrderSide.SELL
    )
    result.append(
        OnlyPlannedExecutionIntent(
            OnlyExecutionIntent(
                order_side,
                side,
                effect,
                exposure_constraint=(
                    OnlyExposureConstraint.REDUCE_ONLY
                    if effect is OnlyPositionEffect.CLOSE
                    else OnlyExposureConstraint.NONE
                ),
            ),
            abs(desired - current),
        )
    )


__all__ = [
    "OnlyExposureState",
    "OnlyPlannedExecutionIntent",
    "only_plan_hedged_target_exposure",
    "only_plan_target_exposure",
]
