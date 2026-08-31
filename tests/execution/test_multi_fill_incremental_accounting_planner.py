from dataclasses import replace
from decimal import Decimal

from onlyalpha.account.enums import OnlyAccountReservationState
from onlyalpha.broker import OnlyBrokerUpdateId
from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.value import OnlyQuantity
from onlyalpha.strategy_ledger.enums import OnlyStrategyCashReservationState
from tests.execution.support.generic_t0_trade_harness import (
    OnlyTestGenericT0Scenario,
    _environment,
    _trade_update,
)
from tests.integration_demo.environment import DAY_ONE


def test_three_fills_commit_three_incremental_transactions() -> None:
    scenario = OnlyTestGenericT0Scenario("three-fill")
    env = _environment(scenario)
    env.start()
    for minute in range(3):
        env.process_bar(DAY_ONE, minute, "10.00")
    submitted = env.submit_buy(request_id="three-fill", quantity="1000")
    assert submitted.order_id is not None

    expected_statuses = (
        OnlyOrderStatus.PARTIALLY_FILLED,
        OnlyOrderStatus.PARTIALLY_FILLED,
        OnlyOrderStatus.FILLED,
    )
    expected_quantities = (Decimal("300"), Decimal("700"), Decimal("1000"))
    expected_active = (1, 1, 0)
    updates = []
    for index, quantity in enumerate(("300", "400", "300"), start=1):
        update = _trade_update(env, scenario, suffix=str(index), fill_price="9.90")
        update = replace(update, fill=replace(update.fill, quantity=OnlyQuantity(Decimal(quantity), 0)))
        updates.append(update)
        result = env.runtime.execution_processor.process(update)
        assert result.status.value == "APPLIED", result.failure
        order = env.runtime.order_manager.require_snapshot(submitted.order_id)
        assert order.status is expected_statuses[index - 1]
        assert order.filled_quantity.value == expected_quantities[index - 1]
        position = result.position_snapshot
        allocation = result.allocation_snapshot
        assert position is not None and allocation is not None
        assert position.total_quantity.value == allocation.total_quantity.value == expected_quantities[index - 1]
        risk = result.risk_snapshot
        assert risk is not None
        assert risk.active_order_count == risk.cluster_active_order_count == expected_active[index - 1]
        account = result.account_snapshot
        ledger = result.ledger_snapshot
        assert account is not None and ledger is not None
        account_reservation = next(item for item in account.reservations if item.order_id == submitted.order_id)
        strategy_reservation = next(item for item in ledger.reservations if item.order_id == submitted.order_id)
        if index < 3:
            assert account_reservation.state is OnlyAccountReservationState.PARTIALLY_CONSUMED
            assert strategy_reservation.state is OnlyStrategyCashReservationState.PARTIALLY_CONSUMED
        else:
            assert account_reservation.state in {
                OnlyAccountReservationState.CONSUMED,
                OnlyAccountReservationState.RELEASED,
            }
            assert strategy_reservation.state in {
                OnlyStrategyCashReservationState.CONSUMED,
                OnlyStrategyCashReservationState.RELEASED,
            }

    all_records = env.runtime.execution_transaction_query.records(env.runtime.config.runtime_id)
    assert len(all_records) == 5
    records = tuple(item for item in all_records if item.operation_kind.value == "TRADE_FILL")
    assert len(records) == 3
    assert tuple(item.fact.fill_index for item in records) == (1, 2, 3)
    assert all(item.projection_ready for item in records)
    assert tuple(item.fact.terminal_fill for item in records) == (False, False, True)
    assert tuple(item.fact.incremental_fee_charges.amount for item in records) == (
        Decimal("2.97"),
        Decimal("3.96"),
        Decimal("2.97"),
    )
    assert tuple(item.fact.order_cumulative_fee_charges_after.amount for item in records) == (
        Decimal("2.97"),
        Decimal("6.93"),
        Decimal("9.90"),
    )
    assert all(item.fact.incremental_fee_rebates.amount == 0 for item in records)
    assert tuple(item.fact.position_cumulative_open_price_quantity_after for item in records) == (
        Decimal("2970.00"),
        Decimal("6930.00"),
        Decimal("9900.00"),
    )
    assert tuple(item.fact.account_reservation_released_delta.amount for item in records[:2]) == (0, 0)
    assert records[2].fact.account_reservation_released_delta.amount == Decimal("100.10")
    assert tuple(item.fact.risk_reservation_quantity_consumed_delta.value for item in records) == (
        Decimal("300"),
        Decimal("400"),
        Decimal("300"),
    )
    release_events = tuple(
        event.event_type.value
        for record in records
        for event in record.outbox_events
        if event.event_type.value.endswith("RESERVATION_RELEASED")
    )
    assert release_events == (
        "ACCOUNT_CASH_RESERVATION_RELEASED",
        "STRATEGY_CASH_RESERVATION_RELEASED",
    )

    authority_before_duplicate = (
        env.runtime.order_manager.require_snapshot(submitted.order_id),
        env.runtime.order_fee_accrual_manager.get(submitted.order_id),
        env.runtime.account_manager.list_accounts()[0],
        env.runtime.risk_service.get_snapshot(
            env.runtime.order_manager.require_snapshot(submitted.order_id).cluster_id
        ),
    )
    duplicate = env.runtime.execution_processor.process(updates[-1])
    assert duplicate.status.value == "DUPLICATE"
    assert len(env.runtime.execution_transaction_query.records(env.runtime.config.runtime_id)) == 5
    conflict_update = replace(
        updates[-1],
        update_id=OnlyBrokerUpdateId("three-fill-conflict"),
        fill=replace(updates[-1].fill, quantity=OnlyQuantity(Decimal("299"), 0)),
    )
    conflict = env.runtime.execution_processor.process(conflict_update)
    assert conflict.status.value == "REJECTED"
    assert conflict.failure is not None and "FILL_IDENTITY_CONFLICT" in conflict.failure.message
    assert (
        env.runtime.order_manager.require_snapshot(submitted.order_id),
        env.runtime.order_fee_accrual_manager.get(submitted.order_id),
        env.runtime.account_manager.list_accounts()[0],
        env.runtime.risk_service.get_snapshot(
            env.runtime.order_manager.require_snapshot(submitted.order_id).cluster_id
        ),
    ) == authority_before_duplicate
