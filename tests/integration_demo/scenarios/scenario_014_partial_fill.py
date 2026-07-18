from datetime import date
from decimal import Decimal

from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.value import OnlyQuantity

from ..environment import DAY_ONE, OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    partial = OnlyIntegrationEnvironment(maximum_fill_quantity=OnlyQuantity(Decimal("40"), 0))
    partial.start()
    for minute in range(3):
        partial.process_bar(DAY_ONE, minute, "10.00")
    submitted = partial.submit_buy()
    partial.process_bar(date(2026, 1, 5), 4, "10.00")
    snapshot = partial.runtime.order_manager.require_snapshot(submitted.order_id)  # type: ignore[arg-type]
    account = partial.runtime.account_manager.list_accounts()[0]

    assert snapshot.status is OnlyOrderStatus.PARTIALLY_FILLED
    assert snapshot.filled_quantity.value == Decimal("40")
    assert account.cash.frozen_cash.amount == Decimal("600.00")
    risk_reservation = partial.runtime.risk_service.reservations.get_for_order(snapshot.order_id)
    assert risk_reservation is not None
    assert risk_reservation.consumed_quantity.value == Decimal("40")
    assert risk_reservation.remaining_quantity.value == Decimal("60")
    assert risk_reservation.remaining_notional.amount == Decimal("600.00")
    assert partial.runtime.broker_gateway is not None
    assert partial.runtime.broker_gateway.query_account(snapshot.account_id).frozen_cash.amount == Decimal("600.00")
    return env.report_builder.scenario(
        "014", "Virtual Broker 部分成交", "40/100 成交后 Local 与 Broker Reservation 保持一致"
    )
