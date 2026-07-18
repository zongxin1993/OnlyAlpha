from decimal import Decimal

from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.execution import OnlyCancelOrderRequest
from onlyalpha.domain.identifiers import OnlyOrderRequestId
from onlyalpha.domain.value import OnlyQuantity

from ..environment import DAY_ONE, OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    partial = OnlyIntegrationEnvironment(maximum_fill_quantity=OnlyQuantity(Decimal("40"), 0))
    partial.start()
    for minute in range(3):
        partial.process_bar(DAY_ONE, minute, "10.00")
    submitted = partial.submit_buy()
    assert submitted.order_id is not None
    partial.process_bar(DAY_ONE, 4, "10.00")
    assert partial.cluster.context is not None
    partial.cluster.context.orders.cancel(
        OnlyCancelOrderRequest(
            OnlyOrderRequestId("partial-cancel"),
            submitted.order_id,
            "cancel remaining 60",
        )
    )
    assert partial.runtime.broker_gateway is not None
    partial.runtime.broker_gateway.run_due()
    partial.runtime.drain_broker_inbound()
    order = partial.runtime.order_manager.require_snapshot(submitted.order_id)
    account = partial.runtime.account_manager.list_accounts()[0]
    risk = partial.runtime.risk_service.reservations.get_for_order(submitted.order_id)
    assert order.status is OnlyOrderStatus.CANCELLED
    assert order.filled_quantity.value == Decimal("40")
    assert account.cash.frozen_cash.amount == Decimal("0.00")
    assert risk is not None and risk.state.value == "RELEASED"
    return env.report_builder.scenario(
        "023",
        "部分成交后撤单",
        "已成交 40 保留，剩余 60 的 Account/Strategy/Risk Reservation 只释放一次",
    )
