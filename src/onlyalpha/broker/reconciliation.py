"""Provider-neutral Broker reconciliation protocol and readiness authority."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from onlyalpha.broker.enums import OnlyBrokerConnectionState
from onlyalpha.broker.identifiers import OnlyBrokerUpdateId
from onlyalpha.broker.inbound import OnlyBrokerInboundQueue
from onlyalpha.broker.updates import OnlyBrokerInboundUpdate
from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.identifiers import OnlyClientOrderId, OnlyOrderId, OnlyVenueOrderId
from onlyalpha.domain.time import OnlyTimestamp


class OnlyBrokerCommandEvidenceKind(StrEnum):
    INTENT_DURABLE = "INTENT_DURABLE"
    DISPATCHED = "DISPATCHED"
    KNOWN_RESULT = "KNOWN_RESULT"
    UNKNOWN = "UNKNOWN"
    RECONCILIATION_STARTED = "RECONCILIATION_STARTED"
    RESOLVED = "RESOLVED"


@dataclass(frozen=True, slots=True)
class OnlyBrokerCommandEvidence(OnlyDomainModel):
    schema_version = 1

    evidence_id: str
    kind: OnlyBrokerCommandEvidenceKind
    order_id: OnlyOrderId
    client_order_id: OnlyClientOrderId
    venue_order_id: OnlyVenueOrderId | None
    occurred_at: OnlyTimestamp
    detail_code: str = ""

    def __post_init__(self) -> None:
        if not self.evidence_id or any(character.isspace() for character in self.evidence_id):
            raise ValueError("BROKER_COMMAND_EVIDENCE_ID_INVALID")


class OnlyBrokerCommandEvidenceStore(Protocol):
    def append(self, evidence: OnlyBrokerCommandEvidence) -> None: ...

    def load(self) -> tuple[OnlyBrokerCommandEvidence, ...]: ...


class OnlyBrokerFactApplicationStatus(StrEnum):
    APPLIED = "APPLIED"
    DUPLICATE = "DUPLICATE"


@dataclass(frozen=True, slots=True)
class OnlyBrokerFactApplicationReceipt(OnlyDomainModel):
    update_id: OnlyBrokerUpdateId
    status: OnlyBrokerFactApplicationStatus


class OnlyDurableBrokerCommandEvidenceStore:
    """Append-only fsync'd evidence; it is not an Order projection authority."""

    def __init__(self, path: Path) -> None:
        if not path.is_absolute():
            raise ValueError("BROKER_EVIDENCE_PATH_MUST_BE_ABSOLUTE")
        self._path = path

    def append(self, evidence: OnlyBrokerCommandEvidence) -> None:
        loaded = self.load()
        existing = {item.evidence_id: item for item in loaded}
        prior = existing.get(evidence.evidence_id)
        if prior is not None:
            if prior != evidence:
                raise ValueError("BROKER_COMMAND_EVIDENCE_IDENTITY_CONFLICT")
            return
        self._validate_records((*loaded, evidence))
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            json.dumps(
                {
                    "schema_version": evidence.schema_version,
                    "evidence_id": evidence.evidence_id,
                    "kind": evidence.kind.value,
                    "order_id": str(evidence.order_id),
                    "client_order_id": str(evidence.client_order_id),
                    "venue_order_id": None if evidence.venue_order_id is None else str(evidence.venue_order_id),
                    "occurred_at_unix_nanos": evidence.occurred_at.unix_nanos,
                    "detail_code": evidence.detail_code,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        descriptor = os.open(self._path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def load(self) -> tuple[OnlyBrokerCommandEvidence, ...]:
        if not self._path.exists():
            return ()
        records: list[OnlyBrokerCommandEvidence] = []
        for line_number, line in enumerate(self._path.read_bytes().splitlines(), 1):
            try:
                raw = json.loads(line)
                records.append(
                    OnlyBrokerCommandEvidence(
                        str(raw["evidence_id"]),
                        OnlyBrokerCommandEvidenceKind(str(raw["kind"])),
                        OnlyOrderId(str(raw["order_id"])),
                        OnlyClientOrderId(str(raw["client_order_id"])),
                        None if raw.get("venue_order_id") is None else OnlyVenueOrderId(str(raw["venue_order_id"])),
                        OnlyTimestamp.from_unix_nanos(int(raw["occurred_at_unix_nanos"])),
                        str(raw.get("detail_code", "")),
                    )
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"BROKER_COMMAND_EVIDENCE_CORRUPT: line {line_number}") from exc
        self._validate_records(tuple(records))
        return tuple(records)

    @staticmethod
    def _validate_records(records: tuple[OnlyBrokerCommandEvidence, ...]) -> None:
        identities = tuple(item.evidence_id for item in records)
        if len(set(identities)) != len(identities):
            raise ValueError("BROKER_COMMAND_EVIDENCE_DUPLICATE_ID")
        client_by_order: dict[OnlyOrderId, OnlyClientOrderId] = {}
        order_by_client: dict[OnlyClientOrderId, OnlyOrderId] = {}
        order_by_venue: dict[OnlyVenueOrderId, OnlyOrderId] = {}
        for item in records:
            if client_by_order.setdefault(item.order_id, item.client_order_id) != item.client_order_id:
                raise ValueError("BROKER_COMMAND_EVIDENCE_ORDER_CLIENT_CONFLICT")
            if order_by_client.setdefault(item.client_order_id, item.order_id) != item.order_id:
                raise ValueError("BROKER_COMMAND_EVIDENCE_CLIENT_ORDER_CONFLICT")
            if (
                item.venue_order_id is not None
                and order_by_venue.setdefault(item.venue_order_id, item.order_id) != item.order_id
            ):
                raise ValueError("BROKER_COMMAND_EVIDENCE_VENUE_ORDER_CONFLICT")


@dataclass(frozen=True, slots=True)
class OnlyBrokerReadinessSnapshot(OnlyDomainModel):
    transport_usable: bool
    authenticated: bool
    account_scope_established: bool
    discovery_complete: bool
    reconciliation_converged: bool
    unresolved_unknown_count: int
    identity_conflict: bool
    stream_trusted: bool

    @property
    def state(self) -> OnlyBrokerConnectionState:
        if self.identity_conflict:
            return OnlyBrokerConnectionState.FAILED
        if self.ready:
            return OnlyBrokerConnectionState.READY
        if self.transport_usable:
            return OnlyBrokerConnectionState.CONNECTED
        return OnlyBrokerConnectionState.DISCONNECTED

    @property
    def ready(self) -> bool:
        return (
            self.transport_usable
            and self.authenticated
            and self.account_scope_established
            and self.discovery_complete
            and self.reconciliation_converged
            and self.unresolved_unknown_count == 0
            and not self.identity_conflict
            and self.stream_trusted
        )


class OnlyBrokerReadinessAuthority:
    def __init__(self) -> None:
        self._transport = False
        self._authenticated = False
        self._account = False
        self._discovery = False
        self._converged = False
        self._unknown: set[OnlyOrderId] = set()
        self._identity_conflict = False
        self._stream = False

    @property
    def snapshot(self) -> OnlyBrokerReadinessSnapshot:
        return OnlyBrokerReadinessSnapshot(
            self._transport,
            self._authenticated,
            self._account,
            self._discovery,
            self._converged,
            len(self._unknown),
            self._identity_conflict,
            self._stream,
        )

    def transport_connected(self) -> None:
        self._transport = True
        self._converged = False

    def authenticated(self) -> None:
        if not self._transport:
            raise RuntimeError("BROKER_AUTH_WITHOUT_TRANSPORT")
        self._authenticated = True

    def account_scope_established(self) -> None:
        if not self._authenticated:
            raise RuntimeError("BROKER_ACCOUNT_SCOPE_WITHOUT_AUTH")
        self._account = True

    def discovery_completed(self) -> None:
        if not self._account:
            raise RuntimeError("BROKER_DISCOVERY_WITHOUT_ACCOUNT_SCOPE")
        self._discovery = True

    def mark_unknown(self, order_id: OnlyOrderId) -> None:
        self._unknown.add(order_id)
        self._converged = False

    def resolve_unknown(self, order_id: OnlyOrderId) -> None:
        if order_id not in self._unknown:
            raise RuntimeError("BROKER_UNKNOWN_RESOLUTION_UNPROVEN")
        self._unknown.remove(order_id)

    def reconciliation_converged(self) -> None:
        if not self._discovery or self._unknown or self._identity_conflict:
            raise RuntimeError("BROKER_RECONCILIATION_CONVERGENCE_UNPROVEN")
        self._converged = True

    def stream_trusted(self) -> None:
        if not self._converged:
            raise RuntimeError("BROKER_STREAM_TRUST_BEFORE_RECONCILIATION")
        self._stream = True

    def stream_lost(self) -> None:
        self._stream = False
        self._converged = False

    def identity_conflict(self) -> None:
        self._identity_conflict = True
        self._converged = False
        self._stream = False

    def disconnected(self) -> None:
        self._transport = False
        self._authenticated = False
        self._account = False
        self._discovery = False
        self._converged = False
        self._stream = False


class OnlyBrokerVenueDiscoveryPort(Protocol):
    def discover_order(self, order: OnlyOrderSnapshot) -> tuple[OnlyBrokerInboundUpdate, ...]: ...

    def verify_order(self, order: OnlyOrderSnapshot) -> bool: ...


class OnlyBrokerReconciliationCoordinator:
    """Discovers external facts and only appends them to the existing inbound pipeline."""

    def __init__(
        self,
        discovery: OnlyBrokerVenueDiscoveryPort,
        inbound: OnlyBrokerInboundQueue,
        readiness: OnlyBrokerReadinessAuthority,
        evidence: OnlyBrokerCommandEvidenceStore,
        now: Callable[[], OnlyTimestamp],
    ) -> None:
        self._discovery = discovery
        self._inbound = inbound
        self._readiness = readiness
        self._evidence = evidence
        self._now = now
        self._sequence = len(evidence.load())
        self._pending: dict[OnlyOrderId, tuple[OnlyBrokerInboundUpdate, ...]] = {}

    def reconcile_unknown(self, order: OnlyOrderSnapshot) -> tuple[OnlyBrokerInboundUpdate, ...]:
        if order.order_id in self._pending:
            raise RuntimeError("BROKER_RECONCILIATION_FACTS_AWAITING_ACK")
        self._append(OnlyBrokerCommandEvidenceKind.RECONCILIATION_STARTED, order)
        updates = self._discovery.discover_order(order)
        if not updates:
            return ()
        for update in updates:
            update_order_id = getattr(update, "order_id", None)
            if update_order_id != order.order_id:
                self._readiness.identity_conflict()
                raise ValueError("BROKER_RECONCILIATION_ORDER_IDENTITY_CONFLICT")
            self._inbound.put(update)
        self._pending[order.order_id] = updates
        return updates

    def acknowledge_unknown(
        self,
        order: OnlyOrderSnapshot,
        receipts: tuple[OnlyBrokerFactApplicationReceipt, ...],
    ) -> None:
        pending = self._pending.get(order.order_id)
        if pending is None:
            raise RuntimeError("BROKER_RECONCILIATION_ACK_WITHOUT_PENDING_FACTS")
        expected = tuple(update.update_id for update in pending)
        received = tuple(receipt.update_id for receipt in receipts)
        if len(set(received)) != len(received) or set(received) != set(expected):
            raise RuntimeError("BROKER_RECONCILIATION_ACK_SET_MISMATCH")
        if not self._discovery.verify_order(order):
            raise RuntimeError("BROKER_RECONCILIATION_CONVERGENCE_UNPROVEN")
        self._readiness.resolve_unknown(order.order_id)
        venue_order_id = next(
            (
                value
                for value in (getattr(update, "venue_order_id", None) for update in pending)
                if isinstance(value, OnlyVenueOrderId)
            ),
            None,
        )
        self._append(OnlyBrokerCommandEvidenceKind.RESOLVED, order, venue_order_id)
        del self._pending[order.order_id]

    def _append(
        self,
        kind: OnlyBrokerCommandEvidenceKind,
        order: OnlyOrderSnapshot,
        venue_order_id: OnlyVenueOrderId | None = None,
    ) -> None:
        self._sequence += 1
        self._evidence.append(
            OnlyBrokerCommandEvidence(
                f"{order.order_id}:{self._sequence:08d}:{kind.value}",
                kind,
                order.order_id,
                order.client_order_id,
                venue_order_id,
                self._now(),
            )
        )


__all__ = [name for name in globals() if name.startswith("Only")]
