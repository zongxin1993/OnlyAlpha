from decimal import Decimal

import pytest

from examples.runtime_context_demo.common import only_demo_runtime
from onlyalpha.domain.enums import OnlyOrderSide, OnlyOrderType
from onlyalpha.domain.execution import OnlyOrderFill, OnlyOrderRequest
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyEngineId,
    OnlyInstrumentId,
    OnlyOrderRequestId,
    OnlyRuntimeId,
    OnlySymbol,
    OnlyTradeId,
    OnlyVenueId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.order.id_generator import OnlySequenceClientOrderIdGenerator, OnlySequenceOrderIdGenerator
from onlyalpha.order.manager import OnlyOrderManager


@pytest.fixture
def order_manager() -> OnlyOrderManager:
    runtime_id = OnlyRuntimeId("runtime")
    return OnlyOrderManager(
        OnlyEngineId("engine"),
        runtime_id,
        OnlySequenceOrderIdGenerator(runtime_id),
        OnlySequenceClientOrderIdGenerator(runtime_id),
    )


@pytest.fixture
def make_runtime():
    return only_demo_runtime


@pytest.fixture
def order_request() -> OnlyOrderRequest:
    return OnlyOrderRequest(
        OnlyOrderRequestId("request-1"),
        OnlyInstrumentId(OnlySymbol("600000"), OnlyVenueId("XSHG")),
        OnlyOrderSide.BUY,
        OnlyOrderType.LIMIT,
        OnlyQuantity(Decimal("4"), 0),
        price=OnlyPrice(Decimal("10.00"), 2),
    )


@pytest.fixture
def created_order(order_manager: OnlyOrderManager, order_request: OnlyOrderRequest):
    return order_manager.create_order(
        order_request,
        OnlyClusterId("cluster-a"),
        OnlyAccountId("account"),
        OnlyTimestamp.from_unix_nanos(1),
    )


def only_fill(order_id, trade_id: str, quantity: str, price: str, timestamp: int) -> OnlyOrderFill:
    return OnlyOrderFill(
        OnlyTradeId(trade_id),
        order_id,
        OnlyPrice(Decimal(price), 2),
        OnlyQuantity(Decimal(quantity), 0),
        OnlyTimestamp.from_unix_nanos(timestamp),
        OnlyTimestamp.from_unix_nanos(timestamp),
    )
