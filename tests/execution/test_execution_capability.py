from dataclasses import replace

import pytest

from onlyalpha.account.enums import OnlyAccountType
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderType
from onlyalpha.domain.trading import OnlyExposureConstraint
from onlyalpha.execution import (
    ONLY_READABLE_EXECUTION_SUPPORT_POLICY_VERSIONS,
    OnlyExecutionCapability,
    OnlyExecutionCapabilityResolver,
    OnlyExecutionReservationShape,
    OnlyExecutionSupportContext,
    OnlyExecutionSupportReason,
)
from onlyalpha.market.models import OnlyPositionEffect
from onlyalpha.position.enums import OnlyPositionMode, OnlyPositionSide
from onlyalpha.transaction import OnlyRuntimeOperationKind
from tests.execution.factories.transaction_factory import only_test_execution_fact_draft


def _buy_open(**changes: object) -> OnlyExecutionSupportContext:
    context = OnlyExecutionSupportContext(
        operation_kind=OnlyRuntimeOperationKind.TRADE_FILL,
        account_type=OnlyAccountType.CASH,
        order_type=OnlyOrderType.LIMIT,
        order_side=OnlyOrderSide.BUY,
        offset=OnlyOffset.OPEN,
        position_side=OnlyPositionSide.LONG,
        position_effect=OnlyPositionEffect.OPEN,
        position_mode=OnlyPositionMode.NETTING,
        has_margin=False,
        account_ledger_parity=True,
        reservations=OnlyExecutionReservationShape(True, True, False, False, True),
    )
    return replace(context, **changes)


def _sell_close(**changes: object) -> OnlyExecutionSupportContext:
    context = replace(
        _buy_open(),
        order_side=OnlyOrderSide.SELL,
        offset=OnlyOffset.CLOSE,
        position_effect=OnlyPositionEffect.CLOSE,
        reservations=OnlyExecutionReservationShape(False, False, True, False, True),
    )
    return replace(context, **changes)


@pytest.mark.parametrize("context", (_buy_open(), _sell_close()))
def test_cash_long_netting_trade_shapes_are_durable(context: OnlyExecutionSupportContext) -> None:
    decision = OnlyExecutionCapabilityResolver().resolve(context)
    assert decision.capability is OnlyExecutionCapability.DURABLE_TRADE
    assert decision.reason is None
    assert decision.policy_version == "3"
    assert len(decision.fingerprint) == 64


@pytest.mark.parametrize(
    "reservations",
    (
        OnlyExecutionReservationShape(False, True, False, False, True),
        OnlyExecutionReservationShape(True, False, False, False, True),
        OnlyExecutionReservationShape(True, True, False, False, False),
        OnlyExecutionReservationShape(True, True, True, False, True),
    ),
)
def test_buy_open_requires_exact_reservation_shape(reservations: OnlyExecutionReservationShape) -> None:
    decision = OnlyExecutionCapabilityResolver().resolve(_buy_open(reservations=reservations))
    assert decision.capability is OnlyExecutionCapability.UNSUPPORTED
    assert decision.reason is OnlyExecutionSupportReason.RESERVATION_SHAPE_UNSUPPORTED


@pytest.mark.parametrize(
    "reservations",
    (
        OnlyExecutionReservationShape(False, False, False, False, True),
        OnlyExecutionReservationShape(False, False, True, False, False),
        OnlyExecutionReservationShape(True, False, True, False, True),
    ),
)
def test_sell_close_requires_exact_reservation_shape(reservations: OnlyExecutionReservationShape) -> None:
    decision = OnlyExecutionCapabilityResolver().resolve(_sell_close(reservations=reservations))
    assert decision.capability is OnlyExecutionCapability.UNSUPPORTED
    assert decision.reason is OnlyExecutionSupportReason.RESERVATION_SHAPE_UNSUPPORTED


def test_margin_account_can_execute_cash_exchange_shape_without_margin() -> None:
    decision = OnlyExecutionCapabilityResolver().resolve(_buy_open(account_type=OnlyAccountType.MARGIN))

    assert decision.capability is OnlyExecutionCapability.DURABLE_TRADE


@pytest.mark.parametrize(
    ("changes", "reason"),
    (
        ({"order_type": OnlyOrderType.MARKET}, OnlyExecutionSupportReason.ORDER_TYPE_UNSUPPORTED),
        ({"position_side": OnlyPositionSide.SHORT}, OnlyExecutionSupportReason.POSITION_SIDE_UNSUPPORTED),
        ({"position_mode": OnlyPositionMode.HEDGING}, OnlyExecutionSupportReason.POSITION_MODE_UNSUPPORTED),
        ({"has_margin": True}, OnlyExecutionSupportReason.MARGIN_UNSUPPORTED),
        (
            {"reservations": OnlyExecutionReservationShape(True, True, False, True, True)},
            OnlyExecutionSupportReason.RESERVATION_SHAPE_UNSUPPORTED,
        ),
        (
            {"account_ledger_parity": False},
            OnlyExecutionSupportReason.ACCOUNT_LEDGER_PARITY_REQUIRED,
        ),
        (
            {"position_effect": OnlyPositionEffect.AUTO},
            OnlyExecutionSupportReason.POSITION_EFFECT_UNSUPPORTED,
        ),
    ),
)
def test_unsupported_kernel_shapes_fail_closed(changes: dict[str, object], reason: OnlyExecutionSupportReason) -> None:
    decision = OnlyExecutionCapabilityResolver().resolve(_buy_open(**changes))
    assert decision.capability is OnlyExecutionCapability.UNSUPPORTED
    assert decision.reason is reason


@pytest.mark.parametrize(
    "context",
    (
        _buy_open(order_side=OnlyOrderSide.SELL),
        _sell_close(order_side=OnlyOrderSide.BUY),
        _buy_open(offset=OnlyOffset.CLOSE),
        _sell_close(offset=OnlyOffset.OPEN),
    ),
)
def test_unsupported_side_offset_combinations_fail_closed(context: OnlyExecutionSupportContext) -> None:
    decision = OnlyExecutionCapabilityResolver().resolve(context)
    assert decision.capability is OnlyExecutionCapability.UNSUPPORTED
    assert decision.reason is OnlyExecutionSupportReason.ORDER_SEMANTICS_UNSUPPORTED


def test_buy_open_and_sell_close_terminal_are_durable() -> None:
    resolver = OnlyExecutionCapabilityResolver()
    sell_close = resolver.resolve(_sell_close(operation_kind=OnlyRuntimeOperationKind.ORDER_TERMINAL))
    buy_open = resolver.resolve(_buy_open(operation_kind=OnlyRuntimeOperationKind.ORDER_TERMINAL))
    assert sell_close.capability is OnlyExecutionCapability.DURABLE_TERMINAL
    assert sell_close.reason is None
    assert buy_open.capability is OnlyExecutionCapability.DURABLE_TERMINAL
    assert buy_open.reason is None


@pytest.mark.parametrize("context", (_buy_open(), _sell_close()))
def test_buy_open_and_sell_close_accepted_are_durable(context: OnlyExecutionSupportContext) -> None:
    decision = OnlyExecutionCapabilityResolver().resolve(
        replace(context, operation_kind=OnlyRuntimeOperationKind.ORDER_ACCEPTED)
    )
    assert decision.capability is OnlyExecutionCapability.DURABLE_ORDER_ACCEPTED
    assert decision.reason is None
    assert decision.policy_version == "3"


def test_reduce_only_open_fails_closed() -> None:
    decision = OnlyExecutionCapabilityResolver().resolve(
        _buy_open(exposure_constraint=OnlyExposureConstraint.REDUCE_ONLY)
    )
    assert decision.capability is OnlyExecutionCapability.UNSUPPORTED
    assert decision.reason is OnlyExecutionSupportReason.ORDER_SEMANTICS_UNSUPPORTED


@pytest.mark.parametrize(
    ("side", "position_side", "mode"),
    (
        (OnlyOrderSide.BUY, OnlyPositionSide.LONG, OnlyPositionMode.NETTING),
        (OnlyOrderSide.SELL, OnlyPositionSide.SHORT, OnlyPositionMode.NETTING),
        (OnlyOrderSide.BUY, OnlyPositionSide.LONG, OnlyPositionMode.HEDGING),
        (OnlyOrderSide.SELL, OnlyPositionSide.SHORT, OnlyPositionMode.HEDGING),
    ),
)
def test_margin_long_short_open_shapes_are_durable(
    side: OnlyOrderSide,
    position_side: OnlyPositionSide,
    mode: OnlyPositionMode,
) -> None:
    decision = OnlyExecutionCapabilityResolver().resolve(
        _buy_open(
            account_type=OnlyAccountType.MARGIN,
            order_side=side,
            position_side=position_side,
            position_mode=mode,
            has_margin=True,
            reservations=OnlyExecutionReservationShape(False, False, False, True, True),
        )
    )
    assert decision.capability is OnlyExecutionCapability.DURABLE_TRADE
    assert decision.reason is None


def test_support_decision_is_deterministic_and_has_no_market_identity_input() -> None:
    resolver = OnlyExecutionCapabilityResolver()
    context = _buy_open()
    assert resolver.resolve(context) == resolver.resolve(context)
    assert "market" not in context.__dataclass_fields__
    assert "profile" not in context.__dataclass_fields__


def test_v3_writer_keeps_v2_historical_fact_policy_readable() -> None:
    assert ONLY_READABLE_EXECUTION_SUPPORT_POLICY_VERSIONS == frozenset({"2", "3"})
    draft = replace(only_test_execution_fact_draft(), execution_support_policy_version="2")
    committed = draft.finalize(1, draft.ts_init)
    assert committed.execution_support_policy_version == "2"


def test_same_product_evidence_cannot_override_different_semantics() -> None:
    resolver = OnlyExecutionCapabilityResolver()
    supported = resolver.resolve(_buy_open())
    unsupported = resolver.resolve(_buy_open(position_side=OnlyPositionSide.SHORT))
    assert supported != unsupported
    assert supported.capability is OnlyExecutionCapability.DURABLE_TRADE
    assert unsupported.capability is OnlyExecutionCapability.UNSUPPORTED
