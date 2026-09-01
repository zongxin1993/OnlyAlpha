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
from onlyalpha.domain.trading import (
    OnlyCloseScope,
    OnlyExecutionIntent,
    OnlyExposureConstraint,
    OnlyPositionEffect,
)
from onlyalpha.execution.scope import OnlyExecutionPositionScopeResolver
from onlyalpha.position.enums import OnlyPositionSide

INSTRUMENT = OnlyInstrumentId(OnlySymbol("SCOPE"), OnlyVenueId("TEST"))


@pytest.mark.parametrize(
    ("side", "offset", "expected_side", "expected_effect", "expected_close_scope"),
    (
        (OnlyOrderSide.BUY, OnlyOffset.OPEN, OnlyPositionSide.LONG, OnlyPositionEffect.OPEN, OnlyCloseScope.ANY),
        (OnlyOrderSide.SELL, OnlyOffset.OPEN, OnlyPositionSide.SHORT, OnlyPositionEffect.OPEN, OnlyCloseScope.ANY),
        (OnlyOrderSide.SELL, OnlyOffset.CLOSE, OnlyPositionSide.LONG, OnlyPositionEffect.CLOSE, OnlyCloseScope.ANY),
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
            OnlyOffset.CLOSE_TODAY,
            OnlyPositionSide.SHORT,
            OnlyPositionEffect.CLOSE,
            OnlyCloseScope.TODAY,
        ),
        (
            OnlyOrderSide.SELL,
            OnlyOffset.CLOSE_YESTERDAY,
            OnlyPositionSide.LONG,
            OnlyPositionEffect.CLOSE,
            OnlyCloseScope.YESTERDAY,
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
def test_explicit_offset_resolves_one_side_aware_scope(
    side: OnlyOrderSide,
    offset: OnlyOffset,
    expected_side: OnlyPositionSide,
    expected_effect: OnlyPositionEffect,
    expected_close_scope: OnlyCloseScope,
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
    assert scope.close_scope is expected_close_scope
    assert scope.position_key.position_side is expected_side
    assert scope.allocation_key is not None
    assert scope.allocation_key.position_side is expected_side


def test_broker_scope_never_guesses_short_as_long() -> None:
    scope = OnlyExecutionPositionScopeResolver(OnlyRuntimeId("scope-runtime")).resolve_broker_position(
        OnlyAccountId("scope-account"), INSTRUMENT, OnlyPositionSide.SHORT
    )

    assert scope.position_side is OnlyPositionSide.SHORT
    assert scope.position_key.position_side is OnlyPositionSide.SHORT


def test_canonical_reduce_only_short_close_survives_order_scope_resolution() -> None:
    runtime_id = OnlyRuntimeId("scope-runtime")
    intent = OnlyExecutionIntent(
        OnlyOrderSide.BUY,
        OnlyPositionSide.SHORT,
        OnlyPositionEffect.CLOSE,
        exposure_constraint=OnlyExposureConstraint.REDUCE_ONLY,
    )
    order = cast(
        OnlyOrderSnapshot,
        SimpleNamespace(
            runtime_id=runtime_id,
            account_id=OnlyAccountId("scope-account"),
            cluster_id=OnlyClusterId("scope-cluster"),
            instrument_id=INSTRUMENT,
            side=OnlyOrderSide.BUY,
            offset=OnlyOffset.CLOSE,
            execution_intent=intent,
        ),
    )

    scope = OnlyExecutionPositionScopeResolver(runtime_id).resolve_order(order)

    assert scope.position_side is OnlyPositionSide.SHORT
    assert scope.position_effect is OnlyPositionEffect.CLOSE
    assert scope.exposure_constraint is OnlyExposureConstraint.REDUCE_ONLY
