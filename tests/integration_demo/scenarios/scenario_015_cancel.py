from decimal import Decimal

from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.execution import OnlyCancelOrderRequest
from onlyalpha.domain.identifiers import OnlyOrderRequestId

from ..environment import DAY_ONE, OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    cancelled = OnlyIntegrationEnvironment()
    cancelled.start()
    for minute in range(3):
        cancelled.process_bar(DAY_ONE, minute, "10.00")
    submitted = cancelled.submit_buy()
    assert submitted.order_id is not None
    assert cancelled.cluster.context is not None
    cancelled.cluster.context.orders.cancel(
        OnlyCancelOrderRequest(OnlyOrderRequestId("integration-cancel"), submitted.order_id, "scenario cancel")
    )
    cancelled.process_bar(DAY_ONE, 4, "10.00")

    order = cancelled.runtime.order_manager.require_snapshot(submitted.order_id)
    account = cancelled.runtime.account_manager.list_accounts()[0]
    assert order.status is OnlyOrderStatus.CANCELLED
    assert account.cash.frozen_cash.amount == Decimal("0.00")
    assert not cancelled.runtime.risk_service.reservations.snapshot_active()
    return env.report_builder.scenario(
        "015", "Broker 确认撤单", "撤单回报经 Runtime Inbound Queue 释放全部本地 Reservation"
    )
