from decimal import Decimal

import pytest

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.broker.updates import (
    OnlyBrokerOrderCancelledUpdate,
    OnlyBrokerOrderExpiredUpdate,
    OnlyBrokerOrderRejectedUpdate,
)
from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.execution import OnlyOrderRejection
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyOrderId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.execution.enums import OnlyExecutionProcessingStatus
from onlyalpha.execution.terminal_fact import (
    OnlyCommittedTerminalExecutionFact,
    OnlyTerminalEconomicReleaseKind,
)
from onlyalpha.transaction.enums import OnlyRuntimeOperationKind
from onlyalpha.transaction.projection import OnlyRuntimeProjectionComponent
from tests.integration_demo.environment import ACCOUNT_ID, DAY_ONE, OnlyIntegrationEnvironment


def _submitted_buy() -> tuple[OnlyIntegrationEnvironment, OnlyOrderId]:
    environment = OnlyIntegrationEnvironment()
    environment.start()
    for minute in range(3):
        environment.process_bar(DAY_ONE, minute, "10.00")
    submitted = environment.submit_buy(quantity="1000")
    assert submitted.order_id is not None
    return environment, submitted.order_id


def _terminal_update(
    environment: OnlyIntegrationEnvironment,
    order_id: OnlyOrderId,
    terminal: str,
) -> OnlyBrokerOrderCancelledUpdate | OnlyBrokerOrderRejectedUpdate | OnlyBrokerOrderExpiredUpdate:
    order = environment.runtime.order_manager.require_snapshot(order_id)
    environment.runtime.clock.advance_by(1_000_000_000)
    timestamp = OnlyTimestamp.from_unix_nanos(environment.runtime.clock.timestamp_ns())
    common = {
        "runtime_id": order.runtime_id,
        "gateway_id": OnlyBrokerGatewayId("virtual-integration"),
        "account_id": OnlyAccountId(ACCOUNT_ID),
        "update_id": OnlyBrokerUpdateId(f"buy-open-{terminal.lower()}"),
        "source_sequence": (order.last_external_sequence or 0) + 1,
        "ts_event": timestamp,
        "ts_init": timestamp,
        "correlation_id": str(order_id),
        "causation_id": "buy-open-terminal-test",
        "order_id": order_id,
    }
    if terminal == "REJECTED":
        return OnlyBrokerOrderRejectedUpdate(
            **common,
            rejection=OnlyOrderRejection("VENUE_REJECT", "venue rejected remaining quantity"),
        )
    if terminal == "EXPIRED":
        return OnlyBrokerOrderExpiredUpdate(**common)
    return OnlyBrokerOrderCancelledUpdate(**common)


@pytest.mark.parametrize(
    ("terminal", "expected_status"),
    (
        ("CANCELLED", OnlyOrderStatus.CANCELLED),
        ("REJECTED", OnlyOrderStatus.REJECTED),
        ("EXPIRED", OnlyOrderStatus.EXPIRED),
    ),
)
def test_buy_open_terminal_releases_exact_remaining_cash_once(
    terminal: str,
    expected_status: OnlyOrderStatus,
) -> None:
    environment, order_id = _submitted_buy()
    before_account = environment.runtime.account_manager.list_accounts()[0]
    before_reservation = next(item for item in before_account.reservations if item.order_id == order_id)
    update = _terminal_update(environment, order_id, terminal)

    result = environment.runtime.execution_processor.process(update)

    assert result.status is OnlyExecutionProcessingStatus.APPLIED, result.failure
    transactions = environment.runtime.execution_transaction_query.transactions_for_order(
        environment.runtime.config.runtime_id,
        order_id,
    )
    assert tuple(item.operation_kind for item in transactions) == (
        OnlyRuntimeOperationKind.ORDER_INTENT,
        OnlyRuntimeOperationKind.ORDER_ACCEPTED,
        OnlyRuntimeOperationKind.ORDER_TERMINAL,
    )
    terminal_transaction = transactions[-1]
    assert tuple(item.identity.component for item in terminal_transaction.projections) == (
        OnlyRuntimeProjectionComponent.ORDER,
        OnlyRuntimeProjectionComponent.ACCOUNT,
        OnlyRuntimeProjectionComponent.STRATEGY_LEDGER,
        OnlyRuntimeProjectionComponent.ACCOUNT_CASH_RESERVATION,
        OnlyRuntimeProjectionComponent.STRATEGY_CASH_RESERVATION,
        OnlyRuntimeProjectionComponent.RISK_RESERVATION,
        OnlyRuntimeProjectionComponent.RISK,
    )
    assert isinstance(terminal_transaction.fact, OnlyCommittedTerminalExecutionFact)
    fact = terminal_transaction.fact
    assert fact.economic_release_kind is OnlyTerminalEconomicReleaseKind.CASH_RESERVATION
    assert fact.reservation_released_cash == before_reservation.remaining_amount
    assert fact.reservation_released_quantity is None
    assert fact.order_remaining_quantity.value == Decimal("1000")
    assert environment.runtime.order_manager.require_snapshot(order_id).status is expected_status
    after_account = environment.runtime.account_manager.list_accounts()[0]
    after_reservation = next(item for item in after_account.reservations if item.order_id == order_id)
    assert after_reservation.remaining_amount.amount == 0
    assert after_account.cash.order_reserved_cash.amount == 0

    duplicate = environment.runtime.execution_processor.process(update)

    assert duplicate.status is OnlyExecutionProcessingStatus.DUPLICATE
    assert environment.runtime.account_manager.list_accounts()[0] == after_account
    assert (
        environment.runtime.execution_transaction_query.transactions_for_order(
            environment.runtime.config.runtime_id,
            order_id,
        )
        == transactions
    )
