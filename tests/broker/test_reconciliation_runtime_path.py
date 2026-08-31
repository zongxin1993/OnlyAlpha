from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.broker.models import OnlyBrokerOrderSnapshot
from onlyalpha.broker.reconciliation import (
    OnlyBrokerCommandEvidenceKind,
    OnlyBrokerCommandOperation,
    OnlyBrokerFactApplicationStatus,
    OnlyBrokerReadinessAuthority,
    OnlyBrokerReconciliationCoordinator,
    OnlyBrokerVenueDiscoveryResult,
    OnlyBrokerVenuePresence,
    OnlyDurableBrokerCommandEvidenceStore,
)
from onlyalpha.broker.updates import OnlyBrokerOrderCancelledUpdate, OnlyBrokerTradeUpdate
from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.execution import OnlyOrderFill, OnlyOrderSnapshot
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyTradeId, OnlyVenueOrderId, OnlyVenueTradeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from tests.integration_demo.environment import (
    ACCOUNT_ID,
    DAY_ONE,
    OnlyIntegrationEnvironment,
)


class _Discovery:
    def __init__(self, update, verified) -> None:
        self.update = update
        self.verified = verified

    def discover_order(self, order, *, operation=OnlyBrokerCommandOperation.SUBMIT):
        venue_order_id = getattr(self.update, "venue_order_id", None) or getattr(
            getattr(self.update, "fill", None), "venue_order_id", None
        )
        snapshot = OnlyBrokerOrderSnapshot(
            OnlyBrokerGatewayId("placeholder"),
            order.account_id,
            order.order_id,
            order.client_order_id,
            venue_order_id,
            order.instrument_id,
            order.side,
            order.offset,
            order.order_type,
            order.quantity,
            order.filled_quantity,
            order.price,
            order.status,
            order.submitted_at or order.created_at,
            order.updated_at,
            1,
        )
        return OnlyBrokerVenueDiscoveryResult(
            OnlyBrokerVenuePresence.PRESENT,
            order.order_id,
            operation,
            (self.update,),
            "proof",
            "0" * 64,
            order.updated_at,
            snapshot,
        )

    def verify_order(self, order):
        return self.verified(order)


def _submitted_environment() -> tuple[OnlyIntegrationEnvironment, OnlyOrderSnapshot]:
    environment = OnlyIntegrationEnvironment(virtual_broker=False)
    environment.start()
    for minute in range(3):
        environment.process_bar(DAY_ONE, minute, "10.00")
    submitted = environment.submit_buy()
    assert submitted.order_id is not None
    return environment, environment.runtime.order_manager.require_snapshot(submitted.order_id)


def test_terminal_snapshot_first_observation_uses_execution_processor_and_binds_venue_identity() -> None:
    environment, order = _submitted_environment()
    now = OnlyTimestamp.from_unix_nanos(environment.runtime.clock.timestamp_ns())
    update = OnlyBrokerOrderCancelledUpdate(
        runtime_id=order.runtime_id,
        gateway_id=OnlyBrokerGatewayId("placeholder"),
        account_id=order.account_id,
        update_id=OnlyBrokerUpdateId("binance-order:9001:CANCELLED"),
        source_sequence=0,
        ts_event=now,
        ts_init=now,
        correlation_id=str(order.client_order_id),
        causation_id="binance-reconciliation",
        quality_flags=("RECONCILIATION_DISCOVERY", "PROVIDER_SEQUENCE_UNAVAILABLE"),
        order_id=order.order_id,
        venue_order_id=OnlyVenueOrderId("9001"),
    )
    environment.runtime.receive_broker_update(update)
    receipts = environment.runtime.drain_broker_inbound_with_receipts()
    assert [(item.update_id, item.status) for item in receipts] == [
        (update.update_id, OnlyBrokerFactApplicationStatus.APPLIED)
    ]
    converged = environment.runtime.order_manager.require_snapshot(order.order_id)
    assert converged.status is OnlyOrderStatus.CANCELLED
    assert converged.venue_order_id == OnlyVenueOrderId("9001")
    assert not environment.runtime.risk_service.reservations.snapshot_active()
    assert environment.runtime.account_manager.list_accounts()[0].cash.order_reserved_cash.amount == 0

    environment.runtime.receive_broker_update(update)
    duplicate = environment.runtime.drain_broker_inbound_with_receipts()
    assert duplicate[0].status is OnlyBrokerFactApplicationStatus.DUPLICATE
    assert environment.runtime.account_manager.list_accounts()[0].cash.order_reserved_cash.amount == 0


def test_missing_fill_reconciliation_gets_real_runtime_receipt_and_exactly_once_economics(
    tmp_path: Path,
) -> None:
    environment, order = _submitted_environment()
    now = OnlyTimestamp.from_unix_nanos(environment.runtime.clock.timestamp_ns())
    fill = OnlyOrderFill(
        OnlyTradeId("BINANCE:600000:7001"),
        order.order_id,
        OnlyPrice(Decimal("10.00"), 2),
        OnlyQuantity(Decimal("100"), 0),
        now,
        now,
        OnlyVenueTradeId("7001"),
        OnlyVenueOrderId("9001"),
        external_sequence=7001,
        external_event_id="binance-trade:600000:7001",
    )
    update = OnlyBrokerTradeUpdate(
        runtime_id=order.runtime_id,
        gateway_id=OnlyBrokerGatewayId("placeholder"),
        account_id=OnlyAccountId(ACCOUNT_ID),
        update_id=OnlyBrokerUpdateId("binance-trade:600000:7001"),
        source_sequence=7001,
        ts_event=now,
        ts_init=now,
        correlation_id=str(order.client_order_id),
        causation_id="binance-reconciliation",
        quality_flags=("RECONCILIATION_DISCOVERY",),
        order_id=order.order_id,
        fill=fill,
    )
    readiness = OnlyBrokerReadinessAuthority()
    readiness.transport_connected()
    readiness.authenticated()
    readiness.account_scope_established()
    readiness.discovery_completed()
    readiness.mark_unknown(order.order_id)
    coordinator = OnlyBrokerReconciliationCoordinator(
        _Discovery(
            update,
            lambda current: (
                current.status is OnlyOrderStatus.FILLED and current.venue_order_id == OnlyVenueOrderId("9001")
            ),
        ),
        environment.runtime.broker_inbound_queue,
        readiness,
        OnlyDurableBrokerCommandEvidenceStore((tmp_path / "commands.jsonl").resolve()),
        lambda: now,
    )

    coordinator.reconcile_unknown(order)
    receipts = environment.runtime.drain_broker_inbound_with_receipts()
    applied_order = environment.runtime.order_manager.require_snapshot(order.order_id)
    assert applied_order.status is OnlyOrderStatus.FILLED
    assert applied_order.venue_order_id == OnlyVenueOrderId("9001")
    coordinator.acknowledge_unknown(
        applied_order,
        receipts,
    )
    converged = environment.runtime.order_manager.require_snapshot(order.order_id)
    assert converged.status is OnlyOrderStatus.FILLED
    assert converged.venue_order_id == OnlyVenueOrderId("9001")
    assert len(environment.runtime.position_manager.snapshot_all()) == 1
    assert environment.runtime.position_manager.snapshot_all()[0].total_quantity.value == Decimal("100")
    account = environment.runtime.account_manager.list_accounts()[0]
    assert account.cash.order_reserved_cash.amount == 0
    assert account.cash.ledger_cash.amount == Decimal("998999.00")
    assert not environment.runtime.risk_service.reservations.snapshot_active()
    assert readiness.snapshot.unresolved_unknown_count == 0

    environment.runtime.receive_broker_update(update)
    duplicate_receipt = environment.runtime.drain_broker_inbound_with_receipts()
    assert duplicate_receipt[0].status is OnlyBrokerFactApplicationStatus.DUPLICATE
    assert environment.runtime.account_manager.list_accounts()[0] == account


def test_cancel_unknown_reconciles_to_cancelled_after_restart_boundary(tmp_path: Path) -> None:
    environment, order = _submitted_environment()
    now = OnlyTimestamp.from_unix_nanos(environment.runtime.clock.timestamp_ns())
    update = OnlyBrokerOrderCancelledUpdate(
        runtime_id=order.runtime_id,
        gateway_id=OnlyBrokerGatewayId("placeholder"),
        account_id=order.account_id,
        update_id=OnlyBrokerUpdateId("binance-order:9001:CANCELLED"),
        source_sequence=0,
        ts_event=now,
        ts_init=now,
        correlation_id=str(order.client_order_id),
        causation_id="binance-cancel-reconciliation",
        quality_flags=("RECONCILIATION_DISCOVERY", "PROVIDER_SEQUENCE_UNAVAILABLE"),
        order_id=order.order_id,
        venue_order_id=OnlyVenueOrderId("9001"),
    )
    readiness = OnlyBrokerReadinessAuthority()
    readiness.transport_connected()
    readiness.authenticated()
    readiness.account_scope_established()
    readiness.discovery_completed()
    readiness.mark_unknown(f"CANCEL:{order.order_id}")
    store = OnlyDurableBrokerCommandEvidenceStore((tmp_path / "cancel-commands.jsonl").resolve())
    coordinator = OnlyBrokerReconciliationCoordinator(
        _Discovery(
            update,
            lambda current: current.status is OnlyOrderStatus.CANCELLED,
        ),
        environment.runtime.broker_inbound_queue,
        readiness,
        store,
        lambda: now,
    )

    coordinator.reconcile_unknown(order, operation=OnlyBrokerCommandOperation.CANCEL)
    receipts = environment.runtime.drain_broker_inbound_with_receipts()
    cancelled = environment.runtime.order_manager.require_snapshot(order.order_id)
    coordinator.acknowledge_unknown(
        cancelled,
        receipts,
        operation=OnlyBrokerCommandOperation.CANCEL,
    )

    assert cancelled.status is OnlyOrderStatus.CANCELLED
    assert cancelled.venue_order_id == OnlyVenueOrderId("9001")
    assert readiness.snapshot.unresolved_unknown_count == 0
    assert [(item.operation, item.kind) for item in store.load()] == [
        (OnlyBrokerCommandOperation.CANCEL, OnlyBrokerCommandEvidenceKind.RECONCILIATION_STARTED),
        (OnlyBrokerCommandOperation.CANCEL, OnlyBrokerCommandEvidenceKind.RESOLVED),
    ]


def test_cancel_fill_race_converges_to_venue_fill_via_execution_processor(tmp_path: Path) -> None:
    environment, order = _submitted_environment()
    now = OnlyTimestamp.from_unix_nanos(environment.runtime.clock.timestamp_ns())
    fill = OnlyOrderFill(
        OnlyTradeId("BINANCE:600000:7002"),
        order.order_id,
        OnlyPrice(Decimal("10.00"), 2),
        OnlyQuantity(Decimal("100"), 0),
        now,
        now,
        OnlyVenueTradeId("7002"),
        OnlyVenueOrderId("9002"),
        external_sequence=7002,
        external_event_id="binance-trade:600000:7002",
    )
    update = OnlyBrokerTradeUpdate(
        runtime_id=order.runtime_id,
        gateway_id=OnlyBrokerGatewayId("placeholder"),
        account_id=order.account_id,
        update_id=OnlyBrokerUpdateId("binance-trade:600000:7002"),
        source_sequence=7002,
        ts_event=now,
        ts_init=now,
        correlation_id=str(order.client_order_id),
        causation_id="binance-cancel-fill-race",
        quality_flags=("RECONCILIATION_DISCOVERY",),
        order_id=order.order_id,
        fill=fill,
    )
    readiness = OnlyBrokerReadinessAuthority()
    readiness.transport_connected()
    readiness.authenticated()
    readiness.account_scope_established()
    readiness.discovery_completed()
    readiness.mark_unknown(f"CANCEL:{order.order_id}")
    coordinator = OnlyBrokerReconciliationCoordinator(
        _Discovery(update, lambda current: current.status is OnlyOrderStatus.FILLED),
        environment.runtime.broker_inbound_queue,
        readiness,
        OnlyDurableBrokerCommandEvidenceStore((tmp_path / "race-commands.jsonl").resolve()),
        lambda: now,
    )

    coordinator.reconcile_unknown(order, operation=OnlyBrokerCommandOperation.CANCEL)
    receipts = environment.runtime.drain_broker_inbound_with_receipts()
    filled = environment.runtime.order_manager.require_snapshot(order.order_id)
    coordinator.acknowledge_unknown(
        filled,
        receipts,
        operation=OnlyBrokerCommandOperation.CANCEL,
    )

    assert filled.status is OnlyOrderStatus.FILLED
    assert filled.venue_order_id == OnlyVenueOrderId("9002")
    assert environment.runtime.position_manager.snapshot_all()[0].total_quantity.value == Decimal("100")
    assert readiness.snapshot.unresolved_unknown_count == 0
