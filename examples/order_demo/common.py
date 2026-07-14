from decimal import Decimal

from examples.risk_demo.accepted_order_demo import only_risk_demo_harness
from onlyalpha.domain.execution import OnlyOrderFill
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyTradeId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity


def only_demo_components():
    demo = only_risk_demo_harness(runtime_id="order-demo", cluster_id="demo")
    return demo.manager, demo.orders, demo.order_publisher, demo.execution, demo.request


def only_submit():
    manager, service, publisher, placeholder, request = only_demo_components()
    result = service.submit(request, OnlyClusterId("demo"), OnlyAccountId("risk-demo-account"))
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
