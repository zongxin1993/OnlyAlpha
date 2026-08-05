from decimal import Decimal

from onlyalpha.execution import OnlyExecutionEventDeliveryMode, OnlyExecutionProcessingStatus
from tests.execution.support.generic_t0_trade_harness import only_test_generic_t0_long_close_context


def test_engine_runtime_long_close_commits_one_durable_transaction_and_projects_all_authorities() -> None:
    environment, context, prepared = only_test_generic_t0_long_close_context(open_quantity="200", close_quantity="100")
    result = environment.runtime.execution_processor.process(context.update)

    assert result.status is OnlyExecutionProcessingStatus.APPLIED
    assert result.delivery_intent.mode is OnlyExecutionEventDeliveryMode.DURABLE_OUTBOX
    records = environment.runtime.execution_transaction_query.records(environment.runtime.config.runtime_id)
    assert len(records) == 2
    close = records[-1]
    assert close.fact == prepared.fact_draft.finalize(close.execution_sequence, close.committed_at)
    assert close.projection_ready
    assert close.fact.position_quantity_before == 200
    assert close.fact.position_quantity_after == 100
    assert close.fact.realized_pnl_delta.amount == Decimal("200.00")

    position = environment.runtime.position_manager.snapshot_all()[0]
    allocation = environment.runtime.allocation_manager.snapshot_all()[0]
    account = environment.runtime.account_manager.list_accounts()[0]
    ledger = environment.runtime.strategy_ledger_manager.require_snapshot(context.strategy_ledger_before.key)
    reservation = environment.runtime.position_reservation_manager.get(context.update.order_id)
    assert position.total_quantity.value == allocation.total_quantity.value == Decimal("100")
    assert position.average_open_price is not None and position.average_open_price.value == Decimal("10.00")
    assert account.cash.ledger_cash == ledger.cash.ledger_cash
    assert account.realized_pnl == ledger.pnl.realized_pnl
    assert reservation is not None and reservation.remaining_quantity.value == 0
