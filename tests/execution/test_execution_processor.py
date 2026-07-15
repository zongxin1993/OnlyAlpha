"""Execution Processor component and direct-upstream/downstream integration tests."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from examples.integration_demo.environment import (
    ACCOUNT_ID,
    CNY,
    DAY_ONE,
    OnlyIntegrationEnvironment,
)
from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.broker.updates import (
    OnlyBrokerOrderAcceptedUpdate,
    OnlyBrokerOrderRejectedUpdate,
    OnlyBrokerTradeUpdate,
)
from onlyalpha.domain.enums import OnlyLiquiditySide
from onlyalpha.domain.execution import OnlyOrderFill, OnlyOrderRejection
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyTradeId,
    OnlyVenueTradeId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha.execution import (
    OnlyExecutionAuditRecord,
    OnlyExecutionMutationStep,
    OnlyExecutionProcessingResult,
    OnlyExecutionProcessingStatus,
)


def _complete_buy(env: OnlyIntegrationEnvironment) -> OnlyExecutionProcessingResult:
    env.start()
    for minute in range(3):
        env.process_bar(DAY_ONE, minute, "10.00")
    env.submit_buy()
    return env.fill_buy()


def test_runtime_owns_one_isolated_processor_and_execution_state() -> None:
    left = OnlyIntegrationEnvironment()
    right = OnlyIntegrationEnvironment()

    assert left.runtime.execution_processor is not right.runtime.execution_processor
    assert left.runtime.execution_audit_store is not right.runtime.execution_audit_store
    assert left.runtime.execution_reconciliation_queue is not right.runtime.execution_reconciliation_queue
    assert left.runtime.execution_update_deduplicator is not right.runtime.execution_update_deduplicator
    assert left.runtime.execution_sequence_tracker is not right.runtime.execution_sequence_tracker


def test_trade_uses_fixed_order_and_builds_consistent_audit_snapshot() -> None:
    env = OnlyIntegrationEnvironment()
    result = _complete_buy(env)

    assert result.status is OnlyExecutionProcessingStatus.APPLIED
    assert tuple(item.step for item in result.mutation_bundle.steps) == (
        OnlyExecutionMutationStep.VALIDATION,
        OnlyExecutionMutationStep.ORDER,
        OnlyExecutionMutationStep.POSITION,
        OnlyExecutionMutationStep.ALLOCATION,
        OnlyExecutionMutationStep.STRATEGY_LEDGER,
        OnlyExecutionMutationStep.ACCOUNT,
        OnlyExecutionMutationStep.RESERVATION,
        OnlyExecutionMutationStep.RISK,
        OnlyExecutionMutationStep.INVARIANT_CHECK,
        OnlyExecutionMutationStep.EVENT,
    )
    assert result.snapshot_bundle.order == env.runtime.order_manager.snapshot_all()[0]
    assert result.snapshot_bundle.account == env.runtime.account_manager.list_accounts()[0]
    assert result.audit_record == next(
        item for item in env.runtime.execution_audit_store.records() if item.update_id == result.update_id
    )
    assert result.audit_record.invariant_result.passed
    assert result.audit_record.to_json() == OnlyExecutionAuditRecord.from_json(result.audit_record.to_json()).to_json()


def test_duplicate_update_and_duplicate_trade_change_no_versions() -> None:
    env = OnlyIntegrationEnvironment()
    applied = _complete_buy(env)
    assert applied.order_snapshot is not None
    order_before = applied.order_snapshot
    account_before = env.runtime.account_manager.list_accounts()[0]
    accepted = next(
        record
        for record in env.runtime.execution_audit_store.records()
        if record.update_type == "OnlyBrokerOrderAcceptedUpdate"
    )
    broker_order = env.runtime.broker_gateway.query_orders(OnlyAccountId(ACCOUNT_ID))[0]  # type: ignore[union-attr]
    timestamp = OnlyTimestamp.from_unix_nanos(env.runtime.clock.timestamp_ns())
    duplicate = OnlyBrokerOrderAcceptedUpdate(
        runtime_id=env.runtime.config.runtime_id,
        gateway_id=OnlyBrokerGatewayId("virtual-integration"),
        account_id=OnlyAccountId(ACCOUNT_ID),
        update_id=accepted.update_id,
        source_sequence=accepted.processing_sequence,
        ts_event=timestamp,
        ts_init=timestamp,
        correlation_id=str(order_before.order_id),
        causation_id="duplicate-test",
        order_id=order_before.order_id,
        venue_order_id=broker_order.venue_order_id,
    )
    env.runtime.receive_broker_update(duplicate)
    result = env.runtime.drain_broker_inbound()[0]

    assert isinstance(result, OnlyExecutionProcessingResult)
    assert result.status is OnlyExecutionProcessingStatus.DUPLICATE
    assert env.runtime.order_manager.require_snapshot(order_before.order_id).version == order_before.version
    assert env.runtime.account_manager.list_accounts()[0].version == account_before.version
    assert not result.generated_events

    broker_trade = env.runtime.broker_gateway.query_trades(OnlyAccountId(ACCOUNT_ID))[0]  # type: ignore[union-attr]
    repeated_trade = OnlyBrokerTradeUpdate(
        runtime_id=env.runtime.config.runtime_id,
        gateway_id=OnlyBrokerGatewayId("virtual-integration"),
        account_id=OnlyAccountId(ACCOUNT_ID),
        update_id=OnlyBrokerUpdateId("same-trade-new-update"),
        source_sequence=999,
        ts_event=timestamp,
        ts_init=timestamp,
        correlation_id=str(order_before.order_id),
        causation_id="duplicate-trade-test",
        order_id=order_before.order_id,
        fill=broker_trade.fill,
    )
    env.runtime.receive_broker_update(repeated_trade)
    trade_result = env.runtime.drain_broker_inbound()[0]
    assert isinstance(trade_result, OnlyExecutionProcessingResult)
    assert trade_result.status is OnlyExecutionProcessingStatus.DUPLICATE
    assert env.runtime.order_manager.require_snapshot(order_before.order_id).version == order_before.version
    assert env.runtime.account_manager.list_accounts()[0].version == account_before.version


def test_late_accepted_does_not_regress_filled_order() -> None:
    env = OnlyIntegrationEnvironment()
    filled = _complete_buy(env)
    assert filled.order_snapshot is not None
    broker_order = env.runtime.broker_gateway.query_orders(OnlyAccountId(ACCOUNT_ID))[0]  # type: ignore[union-attr]
    now = OnlyTimestamp.from_unix_nanos(env.runtime.clock.timestamp_ns())
    late = OnlyBrokerOrderAcceptedUpdate(
        runtime_id=env.runtime.config.runtime_id,
        gateway_id=OnlyBrokerGatewayId("virtual-integration"),
        account_id=OnlyAccountId(ACCOUNT_ID),
        update_id=OnlyBrokerUpdateId("late-accepted-test"),
        source_sequence=0,
        ts_event=now,
        ts_init=now,
        correlation_id=str(filled.order_snapshot.order_id),
        causation_id="late-test",
        order_id=filled.order_snapshot.order_id,
        venue_order_id=broker_order.venue_order_id,
    )
    env.runtime.receive_broker_update(late)
    result = env.runtime.drain_broker_inbound()[0]

    assert isinstance(result, OnlyExecutionProcessingResult)
    assert result.status in {OnlyExecutionProcessingStatus.STALE, OnlyExecutionProcessingStatus.IGNORED}
    assert env.runtime.order_manager.require_snapshot(filled.order_snapshot.order_id).status.value == "FILLED"


def test_out_of_order_trade_requires_reconciliation_before_mutation() -> None:
    env = OnlyIntegrationEnvironment()
    filled = _complete_buy(env)
    assert filled.order_snapshot is not None
    order = filled.order_snapshot
    now = OnlyTimestamp.from_unix_nanos(env.runtime.clock.timestamp_ns())
    stale = OnlyBrokerTradeUpdate(
        runtime_id=env.runtime.config.runtime_id,
        gateway_id=OnlyBrokerGatewayId("virtual-integration"),
        account_id=OnlyAccountId(ACCOUNT_ID),
        update_id=OnlyBrokerUpdateId("stale-trade-update"),
        source_sequence=0,
        ts_event=now,
        ts_init=now,
        correlation_id=str(order.order_id),
        causation_id="stale-trade-test",
        order_id=order.order_id,
        fill=OnlyOrderFill(
            trade_id=OnlyTradeId("stale-new-trade"),
            order_id=order.order_id,
            price=OnlyPrice(Decimal("10.00"), 2),
            quantity=OnlyQuantity(Decimal("1"), 0),
            ts_event=now,
            ts_init=now,
            venue_trade_id=OnlyVenueTradeId("stale-new-venue-trade"),
            venue_order_id=order.venue_order_id,
            fee=OnlyMoney(Decimal("0.00"), CNY),
            liquidity_side=OnlyLiquiditySide.TAKER,
        ),
    )
    versions = (
        order.version,
        env.runtime.account_manager.list_accounts()[0].version,
        env.runtime.position_manager.snapshot_all()[0].version,
    )
    env.runtime.receive_broker_update(stale)
    result = env.runtime.drain_broker_inbound()[0]

    assert isinstance(result, OnlyExecutionProcessingResult)
    assert result.status is OnlyExecutionProcessingStatus.RECONCILIATION_REQUIRED
    assert result.reconciliation_request is not None
    assert versions == (
        env.runtime.order_manager.require_snapshot(order.order_id).version,
        env.runtime.account_manager.list_accounts()[0].version,
        env.runtime.position_manager.snapshot_all()[0].version,
    )


def test_mid_pipeline_failure_discards_success_facts_and_requests_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = OnlyIntegrationEnvironment()
    env.start()
    for minute in range(3):
        env.process_bar(DAY_ONE, minute, "10.00")
    env.submit_buy()
    cursor = len(env.runtime.event_bus.dispatch_results)

    def fail_ledger(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError("injected ledger failure")

    monkeypatch.setattr(env.runtime.strategy_ledger_manager, "apply_trade_accounting", fail_ledger)
    env.process_bar(DAY_ONE, 4, "10.00")
    result = next(
        item
        for item in reversed(env.runtime.broker_results)
        if isinstance(item, OnlyExecutionProcessingResult) and item.update_type == "OnlyBrokerTradeUpdate"
    )
    emitted = tuple(str(item.event.event_type) for item in env.runtime.event_bus.dispatch_results[cursor:])

    assert result.status is OnlyExecutionProcessingStatus.RECONCILIATION_REQUIRED
    assert result.reconciliation_request is not None
    assert "ORDER_FILLED" not in emitted
    assert "POSITION_OPENED" not in emitted
    assert "STRATEGY_TRADE_APPLIED" not in emitted
    assert "EXECUTION_PROCESSING_FAILED" in emitted
    assert "EXECUTION_RECONCILIATION_REQUIRED" in emitted


def test_scope_mismatch_is_rejected_without_state_change() -> None:
    env = OnlyIntegrationEnvironment()
    filled = _complete_buy(env)
    assert filled.order_snapshot is not None
    now = OnlyTimestamp.from_datetime(datetime(2026, 1, 5, 2, 0, tzinfo=UTC))
    update = OnlyBrokerOrderRejectedUpdate(
        runtime_id=type(env.runtime.config.runtime_id)("other-runtime"),
        gateway_id=OnlyBrokerGatewayId("virtual-integration"),
        account_id=OnlyAccountId(ACCOUNT_ID),
        update_id=OnlyBrokerUpdateId("wrong-runtime"),
        source_sequence=999,
        ts_event=now,
        ts_init=now,
        correlation_id=str(filled.order_snapshot.order_id),
        causation_id="scope-test",
        order_id=filled.order_snapshot.order_id,
        rejection=OnlyOrderRejection("TEST", "wrong Runtime"),
    )
    before = env.runtime.order_manager.require_snapshot(filled.order_snapshot.order_id)
    env.runtime.receive_broker_update(update)
    result = env.runtime.drain_broker_inbound()[0]

    assert isinstance(result, OnlyExecutionProcessingResult)
    assert result.status is OnlyExecutionProcessingStatus.REJECTED
    assert env.runtime.order_manager.require_snapshot(before.order_id) == before
    assert not result.generated_events
