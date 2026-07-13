from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from onlyalpha.domain.account import OnlyPnL, OnlyPosition
from onlyalpha.domain.enums import OnlyPositionDirection
from onlyalpha.domain.errors import OnlyStateTransitionError
from onlyalpha.domain.execution import OnlyOrder
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyPositionId
from onlyalpha.domain.value import OnlyMoney, OnlyPrice, OnlyQuantity


def test_partial_fill_cancel_and_position_inventory(buy_request, cny) -> None:
    now = datetime(2024, 1, 1, tzinfo=UTC)
    order = OnlyOrder.initialized(buy_request)
    submitted = order.transition_submitted(now + timedelta(seconds=1))
    accepted = submitted.transition_accepted(now + timedelta(seconds=2), venue_order_id="venue-1")
    partial = accepted.apply_fill(
        filled_quantity=OnlyQuantity(Decimal("1"), 0),
        average_fill_price=OnlyPrice(Decimal("10.00"), 2),
        updated_at=now + timedelta(seconds=3),
        report_id="report-1",
    )
    assert partial.remaining_quantity.value == Decimal("1")
    assert (
        partial.apply_fill(
            filled_quantity=OnlyQuantity(Decimal("1"), 0),
            average_fill_price=OnlyPrice(Decimal("10.00"), 2),
            updated_at=now + timedelta(seconds=3),
            report_id="report-1",
        )
        == partial
    )
    with pytest.raises(OnlyStateTransitionError):
        partial.transition_submitted(now)
    zero = OnlyMoney(Decimal("0.00"), cny)
    position = OnlyPosition(
        OnlyPositionId("p"),
        OnlyAccountId("account"),
        buy_request.instrument_id,
        OnlyPositionDirection.LONG,
        OnlyQuantity(Decimal("1.0"), 1),
        OnlyQuantity(Decimal("0.4"), 1),
        OnlyPrice(Decimal("10.00"), 2),
        OnlyPnL(zero, zero),
        now,
        now,
        frozen_quantity=OnlyQuantity(Decimal("0.6"), 1),
        today_quantity=OnlyQuantity(Decimal("0.4"), 1),
        yesterday_quantity=OnlyQuantity(Decimal("0.6"), 1),
        settlement_currency=cny,
    )
    assert position.available_quantity.value + position.frozen_quantity.value == position.quantity.value
