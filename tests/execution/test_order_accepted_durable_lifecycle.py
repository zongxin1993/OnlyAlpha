from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.broker.updates import OnlyBrokerOrderAcceptedUpdate
from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyOrderId, OnlyRuntimeId, OnlyVenueOrderId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.execution.accepted_fact import OnlyCommittedOrderAcceptedFact
from onlyalpha.execution.accepted_identity import only_capture_execution_order_accepted_authority
from onlyalpha.execution.enums import OnlyExecutionProcessingStatus
from onlyalpha.execution.models import OnlyExecutionProcessingResult
from onlyalpha.execution.trade_planner import OnlyTradeExecutionTransactionPlanner
from onlyalpha.runtime.persistence.store import (
    OnlyInMemoryRuntimePersistenceStore,
    OnlySqliteRuntimePersistenceStore,
)
from onlyalpha.transaction.enums import OnlyRuntimeOperationKind
from onlyalpha.transaction.projection import OnlyRuntimeProjectionComponent
from tests.execution.support.generic_t0_trade_harness import (
    OnlyTestGenericT0Scenario,
    _environment,
    _prepare_environment,
    _trade_update,
    only_test_generic_t0_long_close_context,
    only_test_real_trade_planning_context,
)
from tests.integration_demo.environment import ACCOUNT_ID, DAY_ONE, OnlyIntegrationEnvironment


def _buy_submitted() -> tuple[OnlyIntegrationEnvironment, OnlyOrderId]:
    environment = OnlyIntegrationEnvironment()
    environment.start()
    for minute in range(3):
        environment.process_bar(DAY_ONE, minute, "10.00")
    submitted = environment.submit_buy(quantity="1000")
    assert submitted.order_id is not None
    return environment, submitted.order_id


def _accepted_update(fact: OnlyCommittedOrderAcceptedFact) -> OnlyBrokerOrderAcceptedUpdate:
    return OnlyBrokerOrderAcceptedUpdate(
        runtime_id=fact.runtime_id,
        gateway_id=fact.gateway_id,
        account_id=fact.account_id,
        update_id=fact.broker_update_id,
        source_sequence=fact.source_sequence,
        ts_event=fact.ts_event,
        ts_init=fact.ts_init,
        correlation_id=fact.correlation_id,
        causation_id=fact.causation_id,
        order_id=fact.order_id,
        venue_order_id=fact.venue_order_id,
    )


def test_accepted_identity_is_stable_across_observation_metadata() -> None:
    timestamp = OnlyTimestamp.from_unix_nanos(1_000_000_000)
    update = OnlyBrokerOrderAcceptedUpdate(
        runtime_id=OnlyRuntimeId("runtime"),
        gateway_id=OnlyBrokerGatewayId("gateway"),
        account_id=OnlyAccountId("account"),
        update_id=OnlyBrokerUpdateId("accepted"),
        source_sequence=1,
        ts_event=timestamp,
        ts_init=timestamp,
        correlation_id="correlation",
        causation_id="causation",
        order_id=OnlyOrderId("order"),
        venue_order_id=OnlyVenueOrderId("venue-order"),
    )

    first = only_capture_execution_order_accepted_authority(update)
    repeated = only_capture_execution_order_accepted_authority(update)
    changed = only_capture_execution_order_accepted_authority(replace(update, metadata={"changed": True}))

    assert first == repeated
    assert first.accepted_identity.startswith("EACK-")
    assert changed.accepted_identity == first.accepted_identity
    assert changed.payload_fingerprint == first.payload_fingerprint


def test_buy_open_accepted_has_exact_projection_set_and_is_idempotent() -> None:
    environment, order_id = _buy_submitted()
    records = environment.runtime.execution_transaction_query.transactions_for_order(
        environment.runtime.config.runtime_id,
        order_id,
    )

    assert len(records) == 2
    committed = next(item for item in records if item.operation_kind is OnlyRuntimeOperationKind.ORDER_ACCEPTED)
    assert committed.operation_kind is OnlyRuntimeOperationKind.ORDER_ACCEPTED
    assert isinstance(committed.fact, OnlyCommittedOrderAcceptedFact)
    assert tuple(item.identity.component for item in committed.projections) == (
        OnlyRuntimeProjectionComponent.ORDER,
        OnlyRuntimeProjectionComponent.STRATEGY_LEDGER,
        OnlyRuntimeProjectionComponent.STRATEGY_CASH_RESERVATION,
    )
    before = (
        environment.runtime.order_manager.require_snapshot(order_id),
        environment.runtime.strategy_ledger_manager.list_ledgers(),
        environment.runtime.account_manager.list_accounts(),
    )

    duplicate = environment.runtime.execution_processor.process(_accepted_update(committed.fact))

    assert duplicate.status is OnlyExecutionProcessingStatus.DUPLICATE
    assert (
        environment.runtime.execution_transaction_query.transactions_for_order(
            environment.runtime.config.runtime_id,
            order_id,
        )
        == records
    )
    assert before == (
        environment.runtime.order_manager.require_snapshot(order_id),
        environment.runtime.strategy_ledger_manager.list_ledgers(),
        environment.runtime.account_manager.list_accounts(),
    )


def test_sell_close_accepted_releases_only_account_position_hold() -> None:
    environment, context, _ = only_test_generic_t0_long_close_context(
        open_quantity="1000",
        close_quantity="1000",
        fill_quantity="300",
    )
    records = environment.runtime.execution_transaction_query.transactions_for_order(
        context.update.runtime_id,
        context.update.order_id,
    )

    assert len(records) == 2
    accepted = next(item for item in records if item.operation_kind is OnlyRuntimeOperationKind.ORDER_ACCEPTED)
    assert tuple(item.identity.component for item in accepted.projections) == (
        OnlyRuntimeProjectionComponent.ORDER,
        OnlyRuntimeProjectionComponent.POSITION,
        OnlyRuntimeProjectionComponent.POSITION_RESERVATION,
    )
    position_projection = accepted.projections[1]
    assert position_projection.before.risk_reserved_quantity.value == Decimal("1000")
    assert position_projection.after.risk_reserved_quantity.value == 0
    assert context.position_scope.allocation_key is not None
    allocation = environment.runtime.allocation_manager.get_snapshot(context.position_scope.allocation_key)
    assert allocation is not None
    assert allocation.risk_reserved_quantity.value == Decimal("1000")


@pytest.mark.parametrize("sqlite", (False, True))
def test_accepted_prepared_and_committed_round_trip_in_memory_and_sqlite(
    tmp_path: Path,
    sqlite: bool,
) -> None:
    environment, order_id = _buy_submitted()
    source = next(
        item
        for item in environment.runtime.execution_transaction_query.transactions_for_order(
            environment.runtime.config.runtime_id,
            order_id,
        )
        if item.operation_kind is OnlyRuntimeOperationKind.ORDER_ACCEPTED
    )
    stored = environment.runtime.execution_transaction_query.get_recovery_record_by_update(
        source.runtime_id,
        source.fact.gateway_id,
        source.account_id,
        source.fact.broker_update_id,
    )
    assert stored is not None
    path = tmp_path / "accepted.sqlite3"
    store = OnlySqliteRuntimePersistenceStore(path) if sqlite else OnlyInMemoryRuntimePersistenceStore()

    committed = store.commit(stored.prepared, committed_at=stored.prepared.prepared_at).transaction

    assert store.get_by_transaction_id(stored.prepared.transaction_id) == committed
    assert (
        store.get_by_update(
            committed.runtime_id,
            committed.fact.gateway_id,
            committed.account_id,
            committed.fact.broker_update_id,
        )
        == committed
    )
    store.close()
    if sqlite:
        reopened = OnlySqliteRuntimePersistenceStore(path)
        assert reopened.get_by_transaction_id(stored.prepared.transaction_id) == committed
        reopened.close()


def test_accepted_store_failure_leaves_submitted_authorities_unacknowledged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = OnlyIntegrationEnvironment()
    environment.start()
    for minute in range(3):
        environment.process_bar(DAY_ONE, minute, "10.00")

    original_commit = environment.runtime.execution_transaction_query.commit

    def fail_commit(prepared: object, *, committed_at: OnlyTimestamp) -> object:
        if getattr(prepared, "operation_kind", None) is OnlyRuntimeOperationKind.ORDER_ACCEPTED:
            raise RuntimeError("injected Accepted store failure")
        return original_commit(prepared, committed_at=committed_at)

    monkeypatch.setattr(environment.runtime.execution_transaction_query, "commit", fail_commit)
    submitted = environment.submit_buy(quantity="1000")
    assert submitted.order_id is not None
    accepted_result = next(
        item
        for item in reversed(environment.runtime.broker_results)
        if isinstance(item, OnlyExecutionProcessingResult) and item.update_type == "OnlyBrokerOrderAcceptedUpdate"
    )

    assert accepted_result.status is OnlyExecutionProcessingStatus.FAILED
    assert tuple(item.operation_kind for item in environment.runtime.execution_transaction_query.records()) == (
        OnlyRuntimeOperationKind.ORDER_INTENT,
    )
    assert environment.runtime.order_manager.require_snapshot(submitted.order_id).status is OnlyOrderStatus.SUBMITTED
    ledger = environment.runtime.strategy_ledger_locator.require_snapshot(
        runtime_id=environment.runtime.config.runtime_id,
        account_id=OnlyAccountId(ACCOUNT_ID),
        cluster_id=environment.runtime.order_manager.require_snapshot(submitted.order_id).cluster_id,
        currency=environment.runtime.config.strategy_base_currency,
    )
    reservation = next(item for item in ledger.reservations if item.order_id == submitted.order_id)
    assert reservation.state.value == "ACTIVE"
    assert reservation.stage.value == "SENT_TO_BROKER"


def test_trade_planner_keeps_supporting_submitted_without_explicit_accepted() -> None:
    scenario = OnlyTestGenericT0Scenario("trade-without-accepted")
    environment = _environment(scenario)
    _prepare_environment(environment, scenario)
    assert environment.buy_order is not None and environment.buy_order.order_id is not None
    update = _trade_update(environment, scenario)
    current = only_test_real_trade_planning_context(environment, update)
    accepted = next(
        item
        for item in environment.runtime.execution_transaction_query.transactions_for_order(
            environment.runtime.config.runtime_id,
            environment.buy_order.order_id,
        )
        if item.operation_kind is OnlyRuntimeOperationKind.ORDER_ACCEPTED
    )
    stored = environment.runtime.execution_transaction_query.get_recovery_record_by_update(
        accepted.runtime_id,
        accepted.fact.gateway_id,
        accepted.account_id,
        accepted.fact.broker_update_id,
    )
    assert stored is not None
    projections = {item.identity.component: item for item in stored.prepared.projections}
    submitted = replace(
        current,
        order_before=projections[OnlyRuntimeProjectionComponent.ORDER].before,
        strategy_ledger_before=projections[OnlyRuntimeProjectionComponent.STRATEGY_LEDGER].before,
        strategy_cash_reservation_before=projections[OnlyRuntimeProjectionComponent.STRATEGY_CASH_RESERVATION].before,
    )

    prepared = OnlyTradeExecutionTransactionPlanner().prepare(submitted)

    assert prepared.operation_kind is OnlyRuntimeOperationKind.TRADE_FILL
    assert prepared.fact_draft.fill_index == 1
    assert prepared.projections[0].before.status is OnlyOrderStatus.SUBMITTED
