from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.broker.inbound import OnlyBoundedBrokerInboundQueue
from onlyalpha.broker.reconciliation import (
    OnlyBrokerCommandEvidence,
    OnlyBrokerCommandEvidenceKind,
    OnlyBrokerFactApplicationReceipt,
    OnlyBrokerFactApplicationStatus,
    OnlyBrokerReadinessAuthority,
    OnlyBrokerReconciliationCoordinator,
    OnlyDurableBrokerCommandEvidenceStore,
)
from onlyalpha.broker.updates import OnlyBrokerOrderAcceptedUpdate, OnlyBrokerTradeUpdate
from onlyalpha.domain.enums import OnlyOrderSide, OnlyOrderType
from onlyalpha.domain.execution import OnlyOrderFill, OnlyOrderRequest
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClientOrderId,
    OnlyClusterId,
    OnlyEngineId,
    OnlyInstrumentId,
    OnlyOrderRequestId,
    OnlyRuntimeId,
    OnlyTradeId,
    OnlyVenueOrderId,
    OnlyVenueTradeId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.order.id_generator import OnlySequenceClientOrderIdGenerator, OnlySequenceOrderIdGenerator
from onlyalpha.order.manager import OnlyOrderManager
from tests.order.fee_contract import only_test_zero_fee_contract


def _created():
    runtime_id = OnlyRuntimeId("runtime")
    manager = OnlyOrderManager(
        OnlyEngineId("engine"),
        runtime_id,
        OnlySequenceOrderIdGenerator(runtime_id),
        OnlySequenceClientOrderIdGenerator(runtime_id),
    )
    created = manager.create_order(
        OnlyOrderRequest(
            OnlyOrderRequestId("request-1"),
            OnlyInstrumentId.parse("BTCUSDT.BINANCE"),
            OnlyOrderSide.BUY,
            OnlyOrderType.LIMIT,
            OnlyQuantity(Decimal("4"), 0),
            price=OnlyPrice(Decimal("10.00"), 2),
        ),
        OnlyClusterId("cluster"),
        OnlyAccountId("account"),
        OnlyTimestamp.from_unix_nanos(1),
        only_test_zero_fee_contract,
    )
    return manager, created


def _evidence(kind, order, sequence: int) -> OnlyBrokerCommandEvidence:
    return OnlyBrokerCommandEvidence(
        f"{order.order_id}:{sequence:08d}:{kind.value}",
        kind,
        order.order_id,
        order.client_order_id,
        None,
        OnlyTimestamp.from_unix_nanos(sequence),
    )


def test_durable_command_evidence_is_append_only_restartable_and_conflict_checked(
    tmp_path: Path,
) -> None:
    _, created_order = _created()
    path = (tmp_path / "broker" / "commands.jsonl").resolve()
    store = OnlyDurableBrokerCommandEvidenceStore(path)
    assert store.load() == ()  # C1: no durable intent means no external-order evidence.
    intent = _evidence(OnlyBrokerCommandEvidenceKind.INTENT_DURABLE, created_order.snapshot, 1)
    store.append(intent)  # C2: durable intent exists before dispatch and survives restart.
    assert OnlyDurableBrokerCommandEvidenceStore(path).load() == (intent,)
    store.append(intent)
    assert store.load() == (intent,)
    with pytest.raises(ValueError, match="IDENTITY_CONFLICT"):
        store.append(
            OnlyBrokerCommandEvidence(
                intent.evidence_id,
                OnlyBrokerCommandEvidenceKind.DISPATCHED,
                intent.order_id,
                intent.client_order_id,
                None,
                intent.occurred_at,
            )
        )
    with pytest.raises(ValueError, match="ORDER_CLIENT_CONFLICT"):
        store.append(
            OnlyBrokerCommandEvidence(
                f"{intent.order_id}:00000002:DISPATCHED",
                OnlyBrokerCommandEvidenceKind.DISPATCHED,
                intent.order_id,
                OnlyClientOrderId("different-client"),
                None,
                OnlyTimestamp.from_unix_nanos(2),
            )
        )
    assert store.load() == (intent,)
    path.write_bytes(path.read_bytes() + b"{partial")
    with pytest.raises(ValueError, match="CORRUPT"):
        OnlyDurableBrokerCommandEvidenceStore(path).load()


def test_readiness_requires_every_barrier_and_revokes_on_stream_loss() -> None:
    _, created_order = _created()
    readiness = OnlyBrokerReadinessAuthority()
    assert not readiness.snapshot.ready
    readiness.transport_connected()
    readiness.authenticated()
    readiness.account_scope_established()
    readiness.discovery_completed()
    readiness.mark_unknown(created_order.order_id)
    with pytest.raises(RuntimeError, match="CONVERGENCE_UNPROVEN"):
        readiness.reconciliation_converged()
    readiness.resolve_unknown(created_order.order_id)
    readiness.reconciliation_converged()
    assert not readiness.snapshot.ready
    readiness.stream_trusted()
    assert readiness.snapshot.ready
    readiness.stream_lost()
    assert not readiness.snapshot.ready
    readiness.transport_connected()
    assert not readiness.snapshot.ready


class _Discovery:
    def __init__(self, updates, *, verified: bool = True) -> None:
        self.updates = updates
        self.client_ids = []
        self.verified = verified

    def discover_order(self, order):
        self.client_ids.append(order.client_order_id)
        return self.updates

    def verify_order(self, order):
        del order
        return self.verified


def test_unknown_reconciliation_reuses_client_identity_and_appends_missing_facts(
    tmp_path: Path,
) -> None:
    order_manager, created_order = _created()
    order_manager.mark_submitted(created_order.order_id, OnlyTimestamp.from_unix_nanos(2))
    order = order_manager.require_snapshot(created_order.order_id)
    gateway = OnlyBrokerGatewayId("fake-venue")
    accepted = OnlyBrokerOrderAcceptedUpdate(
        runtime_id=order.runtime_id,
        gateway_id=gateway,
        account_id=order.account_id,
        update_id=OnlyBrokerUpdateId("accepted-venue-1"),
        source_sequence=1,
        ts_event=OnlyTimestamp.from_unix_nanos(3),
        ts_init=OnlyTimestamp.from_unix_nanos(3),
        correlation_id=str(order.client_order_id),
        causation_id="reconcile-query",
        order_id=order.order_id,
        venue_order_id=OnlyVenueOrderId("venue-1"),
    )
    fill = OnlyOrderFill(
        OnlyTradeId("trade-1"),
        order.order_id,
        OnlyPrice(Decimal("10.00"), 2),
        OnlyQuantity(Decimal("1"), 0),
        OnlyTimestamp.from_unix_nanos(4),
        OnlyTimestamp.from_unix_nanos(4),
        OnlyVenueTradeId("venue-trade-1"),
        OnlyVenueOrderId("venue-1"),
        external_sequence=2,
        external_event_id="trade-venue-1",
    )
    trade = OnlyBrokerTradeUpdate(
        runtime_id=order.runtime_id,
        gateway_id=gateway,
        account_id=order.account_id,
        update_id=OnlyBrokerUpdateId("trade-venue-1"),
        source_sequence=2,
        ts_event=fill.ts_event,
        ts_init=fill.ts_init,
        correlation_id=str(order.client_order_id),
        causation_id="reconcile-query",
        order_id=order.order_id,
        fill=fill,
    )
    discovery = _Discovery((accepted, trade))
    inbound = OnlyBoundedBrokerInboundQueue(8)
    readiness = OnlyBrokerReadinessAuthority()
    readiness.transport_connected()
    readiness.authenticated()
    readiness.account_scope_established()
    readiness.discovery_completed()
    readiness.mark_unknown(order.order_id)
    evidence = OnlyDurableBrokerCommandEvidenceStore((tmp_path / "broker.jsonl").resolve())
    coordinator = OnlyBrokerReconciliationCoordinator(
        discovery,
        inbound,
        readiness,
        evidence,
        lambda: OnlyTimestamp.from_unix_nanos(5),
    )
    updates = coordinator.reconcile_unknown(order)
    assert discovery.client_ids == [order.client_order_id]  # C3/C4: no new client identity.
    assert updates == inbound.drain()  # C5: missing venue facts enter the canonical pipeline.
    assert readiness.snapshot.unresolved_unknown_count == 1
    assert [item.kind for item in evidence.load()] == [OnlyBrokerCommandEvidenceKind.RECONCILIATION_STARTED]
    order_manager.apply_accepted(
        accepted.order_id,
        accepted.ts_init,
        accepted.venue_order_id,
        external_sequence=accepted.source_sequence,
        external_event_id=str(accepted.update_id),
        event_time=accepted.ts_event,
    )
    order_manager.apply_fill(fill)
    discovery.verified = False
    receipts = tuple(
        OnlyBrokerFactApplicationReceipt(update.update_id, OnlyBrokerFactApplicationStatus.APPLIED)
        for update in updates
    )
    with pytest.raises(RuntimeError, match="CONVERGENCE_UNPROVEN"):
        coordinator.acknowledge_unknown(order_manager.require_snapshot(order.order_id), receipts)
    assert readiness.snapshot.unresolved_unknown_count == 1
    discovery.verified = True
    coordinator.acknowledge_unknown(
        order_manager.require_snapshot(order.order_id),
        receipts,
    )
    assert readiness.snapshot.unresolved_unknown_count == 0

    conflict_readiness = OnlyBrokerReadinessAuthority()
    conflict_readiness.transport_connected()
    conflict_readiness.authenticated()
    conflict_readiness.account_scope_established()
    conflict_readiness.discovery_completed()
    conflict_readiness.mark_unknown(order.order_id)
    conflict_coordinator = OnlyBrokerReconciliationCoordinator(
        _Discovery((replace(accepted, order_id=type(order.order_id)("other")),)),
        OnlyBoundedBrokerInboundQueue(2),
        conflict_readiness,
        OnlyDurableBrokerCommandEvidenceStore((tmp_path / "conflict.jsonl").resolve()),
        lambda: OnlyTimestamp.from_unix_nanos(6),
    )
    with pytest.raises(ValueError, match="ORDER_IDENTITY_CONFLICT"):
        conflict_coordinator.reconcile_unknown(order)
    assert conflict_readiness.snapshot.identity_conflict
