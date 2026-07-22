from datetime import UTC, datetime
from decimal import Decimal

from onlyalpha.broker import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.broker.updates import OnlyBrokerTradeUpdate
from onlyalpha.domain.execution import OnlyOrderFill
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyOrderId, OnlyRuntimeId, OnlyTradeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.execution import OnlyAppliedTradeFact, OnlyAppliedTradeJournal


def test_applied_trade_journal_is_immutable_ordered_and_trade_idempotent() -> None:
    timestamp = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, tzinfo=UTC))
    update = OnlyBrokerTradeUpdate(
        runtime_id=OnlyRuntimeId("runtime"),
        gateway_id=OnlyBrokerGatewayId("gateway"),
        account_id=OnlyAccountId("account"),
        update_id=OnlyBrokerUpdateId("update"),
        source_sequence=1,
        ts_event=timestamp,
        ts_init=timestamp,
        correlation_id="trade",
        causation_id="order",
        order_id=OnlyOrderId("order"),
        fill=OnlyOrderFill(
            OnlyTradeId("trade"),
            OnlyOrderId("order"),
            OnlyPrice(Decimal("10.00"), 2),
            OnlyQuantity(Decimal("1"), 0),
            timestamp,
            timestamp,
        ),
    )
    fact = OnlyAppliedTradeFact.from_update(update)
    journal = OnlyAppliedTradeJournal()
    journal.append(fact)
    journal.append(fact)

    assert journal.records() == (fact,)
    assert len(journal) == 1
