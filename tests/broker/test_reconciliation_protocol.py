from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.broker.inbound import OnlyBoundedBrokerInboundQueue
from onlyalpha.broker.models import OnlyBrokerOrderSnapshot
from onlyalpha.broker.reconciliation import (
    OnlyBrokerCommandEvidence,
    OnlyBrokerCommandEvidenceKind,
    OnlyBrokerCommandOperation,
    OnlyBrokerFactApplicationReceipt,
    OnlyBrokerFactApplicationStatus,
    OnlyBrokerReadinessAuthority,
    OnlyBrokerReconciliationCoordinator,
    OnlyBrokerVenueDiscoveryResult,
    OnlyBrokerVenuePresence,
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


def test_durable_command_evidence_reads_legacy_schema_one_as_submit(tmp_path: Path) -> None:
    _, created_order = _created()
    order = created_order.snapshot
    path = (tmp_path / "legacy-commands.jsonl").resolve()
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "evidence_id": f"{order.order_id}:00000001:UNKNOWN",
                "kind": "UNKNOWN",
                "order_id": str(order.order_id),
                "client_order_id": str(order.client_order_id),
                "venue_order_id": None,
                "occurred_at_unix_nanos": 1,
                "detail_code": "legacy",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    loaded = OnlyDurableBrokerCommandEvidenceStore(path).load()
    assert len(loaded) == 1
    assert loaded[0].operation.value == "SUBMIT"
    assert loaded[0].command_id == ""
    assert loaded[0].request_payload == ""


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
    def __init__(
        self,
        updates,
        *,
        verified: bool = True,
        presence: OnlyBrokerVenuePresence = OnlyBrokerVenuePresence.PRESENT,
    ) -> None:
        self.updates = updates
        self.client_ids = []
        self.verified = verified
        self.presence = presence

    def discover_order(self, order, *, operation=OnlyBrokerCommandOperation.SUBMIT):
        self.client_ids.append(order.client_order_id)
        venue_order_id = next(
            (
                value
                for update in self.updates
                for value in (
                    getattr(update, "venue_order_id", None),
                    getattr(getattr(update, "fill", None), "venue_order_id", None),
                )
                if value is not None
            ),
            OnlyVenueOrderId("venue-proof"),
        )
        snapshot = OnlyBrokerOrderSnapshot(
            OnlyBrokerGatewayId("fake-venue"),
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
            self.presence,
            order.order_id,
            operation,
            self.updates if self.presence is OnlyBrokerVenuePresence.PRESENT else (),
            "proof",
            "0" * 64,
            order.updated_at,
            snapshot if self.presence is OnlyBrokerVenuePresence.PRESENT else None,
        )

    def verify_order(self, order):
        del order
        return self.verified


@pytest.mark.parametrize("verified, expected_unknown", ((True, 0), (False, 1)))
def test_zero_delta_reconciliation_only_resolves_after_authoritative_verification(
    tmp_path: Path, verified: bool, expected_unknown: int
) -> None:
    manager, created = _created()
    order = manager.require_snapshot(created.order_id)
    readiness = OnlyBrokerReadinessAuthority()
    readiness.mark_unknown(order.order_id)
    store = OnlyDurableBrokerCommandEvidenceStore((tmp_path / f"zero-{verified}.jsonl").resolve())
    coordinator = OnlyBrokerReconciliationCoordinator(
        _Discovery((), verified=verified),
        OnlyBoundedBrokerInboundQueue(4),
        readiness,
        store,
        lambda: OnlyTimestamp.from_unix_nanos(5),
    )

    assert coordinator.reconcile_unknown(order) == ()
    assert readiness.snapshot.unresolved_unknown_count == expected_unknown
    assert [item.kind for item in store.load()] == (
        [OnlyBrokerCommandEvidenceKind.RECONCILIATION_STARTED, OnlyBrokerCommandEvidenceKind.RESOLVED]
        if verified
        else [OnlyBrokerCommandEvidenceKind.RECONCILIATION_STARTED]
    )


@pytest.mark.parametrize(
    "presence, expected_unknown, expected_kinds",
    (
        (
            OnlyBrokerVenuePresence.ABSENT_PROVEN,
            0,
            (
                OnlyBrokerCommandEvidenceKind.RECONCILIATION_STARTED,
                OnlyBrokerCommandEvidenceKind.NO_EXTERNAL_ORDER_PROVEN,
                OnlyBrokerCommandEvidenceKind.RESOLVED,
            ),
        ),
        (
            OnlyBrokerVenuePresence.INCONCLUSIVE,
            1,
            (OnlyBrokerCommandEvidenceKind.RECONCILIATION_STARTED,),
        ),
    ),
)
def test_submit_negative_proof_resolves_but_inconclusive_evidence_does_not(
    tmp_path: Path, presence, expected_unknown: int, expected_kinds
) -> None:
    manager, created = _created()
    order = manager.require_snapshot(created.order_id)
    readiness = OnlyBrokerReadinessAuthority()
    readiness.mark_unknown(order.order_id)
    store = OnlyDurableBrokerCommandEvidenceStore((tmp_path / f"negative-{presence.value}.jsonl").resolve())
    coordinator = OnlyBrokerReconciliationCoordinator(
        _Discovery((), presence=presence),
        OnlyBoundedBrokerInboundQueue(4),
        readiness,
        store,
        lambda: OnlyTimestamp.from_unix_nanos(5),
    )

    assert coordinator.reconcile_unknown(order) == ()
    assert readiness.snapshot.unresolved_unknown_count == expected_unknown
    assert tuple(item.kind for item in store.load()) == expected_kinds


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
