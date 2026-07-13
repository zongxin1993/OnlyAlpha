from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from onlyalpha.domain.enums import (
    OnlyOffset,
    OnlyOrderSide,
    OnlyOrderStatus,
    OnlyOrderType,
    OnlyTimeInForce,
)
from onlyalpha.domain.errors import OnlyStateTransitionError, OnlyValidationError
from onlyalpha.domain.execution import OnlyOrder, OnlyOrderRequest
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyInstrumentId, OnlyOrderId
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity


def test_order_lifecycle_is_immutable_and_validated(instrument_id: OnlyInstrumentId) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    request = OnlyOrderRequest(
        OnlyOrderId("order-1"),
        OnlyAccountId("account-1"),
        OnlyClusterId("cluster-1"),
        instrument_id,
        OnlyOrderSide.BUY,
        OnlyOffset.OPEN,
        OnlyOrderType.LIMIT,
        OnlyQuantity(Decimal("2"), 0),
        OnlyTimeInForce.GTC,
        now,
        limit_price=OnlyPrice(Decimal("10.00"), 2),
    )
    order = OnlyOrder(request, OnlyOrderStatus.INITIALIZED, OnlyQuantity(Decimal("0"), 0), now)
    submitted = order.transition(OnlyOrderStatus.SUBMITTED, now + timedelta(seconds=1))
    accepted = submitted.transition(OnlyOrderStatus.ACCEPTED, now + timedelta(seconds=2))
    filled = accepted.transition(
        OnlyOrderStatus.FILLED,
        now + timedelta(seconds=3),
        filled_quantity=request.quantity,
        average_fill_price=request.limit_price,
    )
    assert order.status is OnlyOrderStatus.INITIALIZED
    assert filled.is_terminal and filled.remaining_quantity.value == 0
    assert OnlyOrder.from_json(filled.to_json()) == filled
    with pytest.raises(OnlyStateTransitionError):
        filled.transition(OnlyOrderStatus.ACCEPTED, now + timedelta(seconds=4))


def test_limit_and_gtd_requests_require_prices_and_expiry(instrument_id: OnlyInstrumentId) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(OnlyValidationError):
        OnlyOrderRequest(
            OnlyOrderId("order-2"),
            OnlyAccountId("a"),
            OnlyClusterId("c"),
            instrument_id,
            OnlyOrderSide.BUY,
            OnlyOffset.OPEN,
            OnlyOrderType.LIMIT,
            OnlyQuantity(Decimal("1"), 0),
            OnlyTimeInForce.GTD,
            now,
        )
