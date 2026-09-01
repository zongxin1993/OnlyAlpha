from dataclasses import replace
from decimal import Decimal

import pytest

from onlyalpha.domain.enums import OnlyMarginMode
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyOrderId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.trading import OnlyPositionSide
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.execution.execution_state import (
    OnlyMarginReservationExecutionStage,
    OnlyMarginReservationExecutionState,
    OnlyMarginReservationExecutionStatus,
)
from onlyalpha.execution.reducers.trade_margin import OnlyMarginReservationTradeReducer
from onlyalpha.market.runtime_rules import OnlyMarginInstruction
from tests.execution.factories.transaction_factory import _TEST_RUNTIME_ID, _currency, _instrument


def _before() -> OnlyMarginReservationExecutionState:
    currency = _currency()
    return OnlyMarginReservationExecutionState(
        "margin-reservation",
        _TEST_RUNTIME_ID,
        OnlyAccountId("account"),
        _instrument(),
        OnlyOrderId("order"),
        currency,
        OnlyMoney(Decimal("10"), currency),
        OnlyMoney(Decimal("10"), currency),
        OnlyMoney(Decimal(0), currency),
        OnlyMoney(Decimal(0), currency),
        OnlyMoney(Decimal(0), currency),
        OnlyMarginReservationExecutionStatus.ACTIVE,
        OnlyMarginReservationExecutionStage.RESERVED,
        OnlyTimestamp(1),
        OnlyTimestamp(1),
        1,
        OnlyMarginMode.ISOLATED,
        "TEST.X:SHORT",
        OnlyPositionSide.SHORT,
    )


def _instruction(amount: str, maintenance: str) -> OnlyMarginInstruction:
    return OnlyMarginInstruction(
        "OCCUPY",
        "account",
        str(_instrument()),
        _currency().code,
        Decimal(amount),
        Decimal(maintenance),
        "order",
        "trade",
        OnlyTimestamp(2),
        OnlyMarginMode.ISOLATED.value,
        "TEST.X:SHORT",
        OnlyPositionSide.SHORT.value,
    )


def _occupied_before() -> OnlyMarginReservationExecutionState:
    currency = _currency()
    return replace(
        _before(),
        remaining_reserved_amount=OnlyMoney(Decimal(0), currency),
        occupied_amount=OnlyMoney(Decimal("10"), currency),
        maintenance_amount=OnlyMoney(Decimal("4"), currency),
        state=OnlyMarginReservationExecutionStatus.OCCUPIED,
        stage=OnlyMarginReservationExecutionStage.OCCUPIED,
    )


def _release_instruction() -> OnlyMarginInstruction:
    return replace(_instruction("0", "0"), action="RELEASE", source_order_id="close-order")


def test_partial_margin_fill_occupies_proportionally_and_preserves_scope() -> None:
    reduction = OnlyMarginReservationTradeReducer().reduce_open(
        _before(),
        _instruction("4", "2"),
        terminal_fill=False,
        projection_sequence=1,
    )

    assert reduction.after.remaining_reserved_amount.amount == Decimal("6")
    assert reduction.after.occupied_amount.amount == Decimal("4")
    assert reduction.after.maintenance_amount.amount == Decimal("2")
    assert reduction.after.position_side is OnlyPositionSide.SHORT
    assert reduction.after.isolation_key == "TEST.X:SHORT"
    assert reduction.reserved_delta.amount == Decimal("-4")
    assert reduction.occupied_delta.amount == Decimal("4")


def test_terminal_margin_fill_releases_unused_reservation() -> None:
    reduction = OnlyMarginReservationTradeReducer().reduce_open(
        _before(),
        _instruction("4", "2"),
        terminal_fill=True,
        projection_sequence=1,
    )

    assert reduction.after.remaining_reserved_amount.amount == 0
    assert reduction.after.occupied_amount.amount == Decimal("4")
    assert reduction.after.released_amount.amount == Decimal("6")
    assert reduction.released_delta.amount == Decimal("6")


def test_margin_fill_fails_atomically_when_reservation_is_insufficient() -> None:
    before = _before()
    with pytest.raises(ValueError, match="MARGIN_RESERVATION_INSUFFICIENT"):
        OnlyMarginReservationTradeReducer().reduce_open(
            before,
            _instruction("11", "5"),
            terminal_fill=False,
            projection_sequence=1,
        )
    assert before == _before()


def test_margin_fill_rejects_position_leg_scope_conflict() -> None:
    before = replace(_before(), position_side=OnlyPositionSide.LONG)
    with pytest.raises(ValueError, match="MARGIN_RESERVATION_SCOPE_CONFLICT"):
        OnlyMarginReservationTradeReducer().reduce_open(
            before,
            _instruction("4", "2"),
            terminal_fill=False,
            projection_sequence=1,
        )


def test_partial_margin_close_releases_occupied_and_maintenance_proportionally() -> None:
    reduction = OnlyMarginReservationTradeReducer().reduce_close(
        _occupied_before(),
        _release_instruction(),
        fill_quantity=Decimal("2"),
        position_quantity_before=Decimal("5"),
        projection_sequence=1,
    )

    assert reduction.after.occupied_amount.amount == Decimal("6")
    assert reduction.after.maintenance_amount.amount == Decimal("2.4")
    assert reduction.after.released_amount.amount == Decimal("4")
    assert reduction.after.state is OnlyMarginReservationExecutionStatus.OCCUPIED
    assert reduction.occupied_delta.amount == Decimal("-4")
    assert reduction.released_delta.amount == Decimal("4")


def test_partial_margin_close_rounds_release_to_currency_precision_and_retains_residual() -> None:
    before = replace(
        _occupied_before(),
        maintenance_amount=OnlyMoney(Decimal("5.00"), _currency()),
    )

    reduction = OnlyMarginReservationTradeReducer().reduce_close(
        before,
        _release_instruction(),
        fill_quantity=Decimal("1"),
        position_quantity_before=Decimal("3"),
        projection_sequence=1,
    )

    assert reduction.released_delta.amount == Decimal("3.33")
    assert reduction.after.occupied_amount.amount == Decimal("6.67")
    assert reduction.after.maintenance_amount.amount == Decimal("3.33")


def test_full_margin_close_releases_all_occupied_authority() -> None:
    reduction = OnlyMarginReservationTradeReducer().reduce_close(
        _occupied_before(),
        _release_instruction(),
        fill_quantity=Decimal("5"),
        position_quantity_before=Decimal("5"),
        projection_sequence=1,
    )

    assert reduction.after.occupied_amount.amount == 0
    assert reduction.after.maintenance_amount.amount == 0
    assert reduction.after.released_amount.amount == Decimal("10")
    assert reduction.after.state is OnlyMarginReservationExecutionStatus.RELEASED
    assert reduction.after.stage is OnlyMarginReservationExecutionStage.RELEASED
