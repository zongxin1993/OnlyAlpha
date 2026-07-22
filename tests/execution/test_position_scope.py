from types import SimpleNamespace
from typing import cast

import pytest

from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide
from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyRuntimeId,
    OnlySymbol,
    OnlyVenueId,
)
from onlyalpha.execution.scope import OnlyExecutionPositionScopeResolver
from onlyalpha.market.models import OnlyPositionEffect
from onlyalpha.position.enums import OnlyPositionSide

INSTRUMENT = OnlyInstrumentId(OnlySymbol("SCOPE"), OnlyVenueId("TEST"))


@pytest.mark.parametrize(
    ("side", "offset", "expected_side", "expected_effect"),
    (
        (OnlyOrderSide.BUY, OnlyOffset.OPEN, OnlyPositionSide.LONG, OnlyPositionEffect.OPEN),
        (OnlyOrderSide.SELL, OnlyOffset.OPEN, OnlyPositionSide.SHORT, OnlyPositionEffect.OPEN),
        (OnlyOrderSide.SELL, OnlyOffset.CLOSE, OnlyPositionSide.LONG, OnlyPositionEffect.CLOSE),
        (OnlyOrderSide.BUY, OnlyOffset.CLOSE, OnlyPositionSide.SHORT, OnlyPositionEffect.CLOSE),
        (OnlyOrderSide.SELL, OnlyOffset.CLOSE_TODAY, OnlyPositionSide.LONG, OnlyPositionEffect.CLOSE),
        (OnlyOrderSide.BUY, OnlyOffset.CLOSE_TODAY, OnlyPositionSide.SHORT, OnlyPositionEffect.CLOSE),
        (OnlyOrderSide.SELL, OnlyOffset.CLOSE_YESTERDAY, OnlyPositionSide.LONG, OnlyPositionEffect.CLOSE),
        (OnlyOrderSide.BUY, OnlyOffset.CLOSE_YESTERDAY, OnlyPositionSide.SHORT, OnlyPositionEffect.CLOSE),
    ),
)
def test_explicit_offset_resolves_one_side_aware_scope(
    side: OnlyOrderSide,
    offset: OnlyOffset,
    expected_side: OnlyPositionSide,
    expected_effect: OnlyPositionEffect,
) -> None:
    runtime_id = OnlyRuntimeId("scope-runtime")
    order = cast(
        OnlyOrderSnapshot,
        SimpleNamespace(
            runtime_id=runtime_id,
            account_id=OnlyAccountId("scope-account"),
            cluster_id=OnlyClusterId("scope-cluster"),
            instrument_id=INSTRUMENT,
            side=side,
            offset=offset,
        ),
    )

    scope = OnlyExecutionPositionScopeResolver(runtime_id).resolve_order(order)

    assert scope.position_side is expected_side
    assert scope.position_effect is expected_effect
    assert scope.position_key.position_side is expected_side
    assert scope.allocation_key is not None
    assert scope.allocation_key.position_side is expected_side


def test_broker_scope_never_guesses_short_as_long() -> None:
    scope = OnlyExecutionPositionScopeResolver(OnlyRuntimeId("scope-runtime")).resolve_broker_position(
        OnlyAccountId("scope-account"), INSTRUMENT, OnlyPositionSide.SHORT
    )

    assert scope.position_side is OnlyPositionSide.SHORT
    assert scope.position_key.position_side is OnlyPositionSide.SHORT
