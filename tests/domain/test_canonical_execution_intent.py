import pytest

from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide
from onlyalpha.domain.trading import (
    OnlyCloseScope,
    OnlyExecutionIntent,
    OnlyExposureConstraint,
    OnlyPositionEffect,
    OnlyPositionSide,
)
from onlyalpha.market.models import OnlyPositionEffect as MarketPositionEffect
from onlyalpha.position.enums import OnlyPositionSide as PositionComponentSide


@pytest.mark.parametrize(
    ("side", "offset", "position_side", "effect", "scope"),
    (
        (OnlyOrderSide.BUY, OnlyOffset.OPEN, OnlyPositionSide.LONG, OnlyPositionEffect.OPEN, OnlyCloseScope.ANY),
        (OnlyOrderSide.SELL, OnlyOffset.CLOSE, OnlyPositionSide.LONG, OnlyPositionEffect.CLOSE, OnlyCloseScope.ANY),
        (OnlyOrderSide.SELL, OnlyOffset.OPEN, OnlyPositionSide.SHORT, OnlyPositionEffect.OPEN, OnlyCloseScope.ANY),
        (OnlyOrderSide.BUY, OnlyOffset.CLOSE, OnlyPositionSide.SHORT, OnlyPositionEffect.CLOSE, OnlyCloseScope.ANY),
        (
            OnlyOrderSide.SELL,
            OnlyOffset.CLOSE_TODAY,
            OnlyPositionSide.LONG,
            OnlyPositionEffect.CLOSE,
            OnlyCloseScope.TODAY,
        ),
        (
            OnlyOrderSide.BUY,
            OnlyOffset.CLOSE_YESTERDAY,
            OnlyPositionSide.SHORT,
            OnlyPositionEffect.CLOSE,
            OnlyCloseScope.YESTERDAY,
        ),
    ),
)
def test_legacy_offset_normalizes_to_one_canonical_intent(
    side: OnlyOrderSide,
    offset: OnlyOffset,
    position_side: OnlyPositionSide,
    effect: OnlyPositionEffect,
    scope: OnlyCloseScope,
) -> None:
    intent = OnlyExecutionIntent.from_offset(side=side, offset=offset)

    assert intent.position_side is position_side
    assert intent.position_effect is effect
    assert intent.close_scope is scope


def test_compatibility_imports_are_the_same_authority() -> None:
    assert MarketPositionEffect is OnlyPositionEffect
    assert PositionComponentSide is OnlyPositionSide


def test_reduce_only_is_orthogonal_and_cannot_open() -> None:
    close = OnlyExecutionIntent(
        OnlyOrderSide.BUY,
        OnlyPositionSide.SHORT,
        OnlyPositionEffect.CLOSE,
        exposure_constraint=OnlyExposureConstraint.REDUCE_ONLY,
    )
    assert close.reduces_exposure

    with pytest.raises(ValueError, match="REDUCE_ONLY_OPEN"):
        OnlyExecutionIntent(
            OnlyOrderSide.SELL,
            OnlyPositionSide.SHORT,
            OnlyPositionEffect.OPEN,
            exposure_constraint=OnlyExposureConstraint.REDUCE_ONLY,
        )


def test_side_effect_conflict_fails_closed() -> None:
    with pytest.raises(ValueError, match="SIDE_EFFECT_CONFLICT"):
        OnlyExecutionIntent(
            OnlyOrderSide.BUY,
            OnlyPositionSide.SHORT,
            OnlyPositionEffect.OPEN,
        )
