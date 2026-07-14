from datetime import UTC, datetime
from decimal import Decimal

from onlyalpha.domain.account import OnlyPnL, OnlyPosition
from onlyalpha.domain.enums import OnlyOrderStatus, OnlyPositionDirection
from onlyalpha.domain.execution import OnlyOrderFill
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyEngineId,
    OnlyPositionId,
    OnlyRuntimeId,
    OnlyTradeId,
    OnlyVenueOrderId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha.order.enums import OnlyOrderApplyResult
from onlyalpha.order.id_generator import OnlySequenceClientOrderIdGenerator, OnlySequenceOrderIdGenerator
from onlyalpha.order.manager import OnlyOrderManager


def test_partial_fill_is_idempotent_and_position_inventory_remains_independent(buy_request, cny) -> None:
    runtime_id = OnlyRuntimeId("runtime")
    manager = OnlyOrderManager(
        OnlyEngineId("engine"),
        runtime_id,
        OnlySequenceOrderIdGenerator(runtime_id),
        OnlySequenceClientOrderIdGenerator(runtime_id),
    )
    now = OnlyTimestamp.from_unix_nanos(1)
    created = manager.create_order(buy_request, OnlyClusterId("cluster"), OnlyAccountId("account"), now)
    manager.mark_submitted(created.order_id, OnlyTimestamp.from_unix_nanos(2))
    manager.apply_accepted(
        created.order_id,
        OnlyTimestamp.from_unix_nanos(3),
        OnlyVenueOrderId("venue-1"),
    )
    fill = OnlyOrderFill(
        OnlyTradeId("trade-1"),
        created.order_id,
        OnlyPrice(Decimal("10.00"), 2),
        OnlyQuantity(Decimal("1"), 0),
        OnlyTimestamp.from_unix_nanos(4),
        OnlyTimestamp.from_unix_nanos(4),
    )
    partial = manager.apply_fill(fill)
    duplicate = manager.apply_fill(fill)
    assert partial.snapshot.status is OnlyOrderStatus.PARTIALLY_FILLED
    assert partial.snapshot.remaining_quantity.value == Decimal("1")
    assert duplicate.apply_result is OnlyOrderApplyResult.DUPLICATE

    dt = datetime(2024, 1, 1, tzinfo=UTC)
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
        dt,
        dt,
        frozen_quantity=OnlyQuantity(Decimal("0.6"), 1),
        today_quantity=OnlyQuantity(Decimal("0.4"), 1),
        yesterday_quantity=OnlyQuantity(Decimal("0.6"), 1),
        settlement_currency=cny,
    )
    assert position.available_quantity.value + position.frozen_quantity.value == position.quantity.value
