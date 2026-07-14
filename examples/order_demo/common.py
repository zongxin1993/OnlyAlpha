from decimal import Decimal

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
from onlyalpha.order.execution.placeholder import OnlyPlaceholderExecutionService
from onlyalpha.order.id_generator import OnlySequenceClientOrderIdGenerator, OnlySequenceOrderIdGenerator
from onlyalpha.order.manager import OnlyOrderManager
from onlyalpha.order.publisher import OnlyInMemoryOrderEventPublisher
from onlyalpha.order.service import OnlyOrderService


def only_demo_components():
    runtime_id = OnlyRuntimeId("order-demo")
    manager = OnlyOrderManager(
        OnlyEngineId("demo-engine"),
        runtime_id,
        OnlySequenceOrderIdGenerator(runtime_id),
        OnlySequenceClientOrderIdGenerator(runtime_id),
    )
    publisher = OnlyInMemoryOrderEventPublisher()
    placeholder = OnlyPlaceholderExecutionService()
    service = OnlyOrderService(
        manager,
        placeholder,
        publisher,
        lambda: OnlyTimestamp.from_unix_nanos(1),
    )
    request = OnlyOrderRequest(
        OnlyOrderRequestId("demo-request"),
        OnlyInstrumentId(OnlySymbol("600000"), OnlyVenueId("XSHG")),
        OnlyOrderSide.BUY,
        OnlyOrderType.LIMIT,
        OnlyQuantity(Decimal("100"), 0),
        price=OnlyPrice(Decimal("10.00"), 2),
    )
    return manager, service, publisher, placeholder, request


def only_submit():
    manager, service, publisher, placeholder, request = only_demo_components()
    result = service.submit(request, OnlyClusterId("demo"), OnlyAccountId("demo"))
    return manager, service, publisher, placeholder, result


def only_fill(order_id, trade_id: str, quantity: str, timestamp: int) -> OnlyOrderFill:
    return OnlyOrderFill(
        OnlyTradeId(trade_id),
        order_id,
        OnlyPrice(Decimal("10.00"), 2),
        OnlyQuantity(Decimal(quantity), 0),
        OnlyTimestamp.from_unix_nanos(timestamp),
        OnlyTimestamp.from_unix_nanos(timestamp),
    )
