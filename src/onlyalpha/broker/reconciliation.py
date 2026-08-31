"""Provider-neutral Broker reconciliation protocol and readiness authority."""

from __future__ import annotations

import hashlib
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
from onlyalpha.broker.models import OnlyBrokerOrderSnapshot
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
    NO_EXTERNAL_ORDER_PROVEN = "NO_EXTERNAL_ORDER_PROVEN"
    RESOLVED = "RESOLVED"


class OnlyBrokerCommandOperation(StrEnum):
    SUBMIT = "SUBMIT"
    CANCEL = "CANCEL"


class OnlyBrokerVenuePresence(StrEnum):
    PRESENT = "PRESENT"
    ABSENT_PROVEN = "ABSENT_PROVEN"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True, slots=True)
class OnlyBrokerVenueDiscoveryResult(OnlyDomainModel):
    presence: OnlyBrokerVenuePresence
    order_id: OnlyOrderId
    operation: OnlyBrokerCommandOperation
    discovered_facts: tuple[OnlyBrokerInboundUpdate, ...]
    proof_id: str
    proof_fingerprint: str
    observed_at: OnlyTimestamp
    authoritative_snapshot: OnlyBrokerOrderSnapshot | None = None

    def __post_init__(self) -> None:
        if not self.proof_id.strip() or len(self.proof_fingerprint) != 64:
            raise ValueError("BROKER_RECONCILIATION_PROOF_INVALID")
        if self.presence is OnlyBrokerVenuePresence.ABSENT_PROVEN and (
            self.authoritative_snapshot is not None or self.discovered_facts
        ):
            raise ValueError("BROKER_ABSENCE_PROOF_CANNOT_CONTAIN_VENUE_FACTS")
        if self.presence is OnlyBrokerVenuePresence.PRESENT and self.authoritative_snapshot is None:
            raise ValueError("BROKER_PRESENT_DISCOVERY_REQUIRES_AUTHORITATIVE_SNAPSHOT")
        if self.presence is OnlyBrokerVenuePresence.INCONCLUSIVE and self.discovered_facts:
            raise ValueError("BROKER_INCONCLUSIVE_DISCOVERY_CANNOT_ASSERT_FACTS")


@dataclass(frozen=True, slots=True)
class OnlyBrokerCommandEvidence(OnlyDomainModel):
    schema_version = 3

    evidence_id: str
    kind: OnlyBrokerCommandEvidenceKind
    order_id: OnlyOrderId
    client_order_id: OnlyClientOrderId
    venue_order_id: OnlyVenueOrderId | None
    occurred_at: OnlyTimestamp
    detail_code: str = ""
    operation: OnlyBrokerCommandOperation = OnlyBrokerCommandOperation.SUBMIT
    command_id: str = ""
    request_payload: str = ""
    request_fingerprint: str = ""
    runtime_intent_transaction_id: str = ""
    runtime_intent_authority_hash: str = ""

    def __post_init__(self) -> None:
        if not self.evidence_id or any(character.isspace() for character in self.evidence_id):
            raise ValueError("BROKER_COMMAND_EVIDENCE_ID_INVALID")
        if self.command_id and any(character.isspace() for character in self.command_id):
            raise ValueError("BROKER_COMMAND_ID_INVALID")
        if self.request_payload:
            fingerprint = hashlib.sha256(self.request_payload.encode("utf-8")).hexdigest()
            if self.request_fingerprint != fingerprint:
                raise ValueError("BROKER_COMMAND_REQUEST_FINGERPRINT_INVALID")
        elif self.request_fingerprint:
            raise ValueError("BROKER_COMMAND_REQUEST_PAYLOAD_MISSING")
        if bool(self.runtime_intent_transaction_id) != bool(self.runtime_intent_authority_hash):
            raise ValueError("BROKER_COMMAND_INTENT_REFERENCE_INCOMPLETE")
        if self.runtime_intent_authority_hash and len(self.runtime_intent_authority_hash) != 64:
            raise ValueError("BROKER_COMMAND_INTENT_AUTHORITY_HASH_INVALID")


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
                    "operation": evidence.operation.value,
                    "command_id": evidence.command_id,
                    "request_payload": evidence.request_payload,
                    "request_fingerprint": evidence.request_fingerprint,
                    "runtime_intent_transaction_id": evidence.runtime_intent_transaction_id,
                    "runtime_intent_authority_hash": evidence.runtime_intent_authority_hash,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        created = not self._path.exists()
        descriptor = os.open(self._path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            remaining = memoryview(payload)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OSError("BROKER_COMMAND_EVIDENCE_SHORT_WRITE")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if created:
            directory = os.open(self._path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)

    def load(self) -> tuple[OnlyBrokerCommandEvidence, ...]:
        if not self._path.exists():
            return ()
        records: list[OnlyBrokerCommandEvidence] = []
        for line_number, line in enumerate(self._path.read_bytes().splitlines(), 1):
            try:
                raw = json.loads(line)
                schema_version = int(raw.get("schema_version", 1))
                if schema_version not in {1, 2, 3}:
                    raise ValueError("BROKER_COMMAND_EVIDENCE_SCHEMA_UNSUPPORTED")
                records.append(
                    OnlyBrokerCommandEvidence(
                        str(raw["evidence_id"]),
                        OnlyBrokerCommandEvidenceKind(str(raw["kind"])),
                        OnlyOrderId(str(raw["order_id"])),
                        OnlyClientOrderId(str(raw["client_order_id"])),
                        None if raw.get("venue_order_id") is None else OnlyVenueOrderId(str(raw["venue_order_id"])),
                        OnlyTimestamp.from_unix_nanos(int(raw["occurred_at_unix_nanos"])),
                        str(raw.get("detail_code", "")),
                        OnlyBrokerCommandOperation(str(raw.get("operation", "SUBMIT"))),
                        str(raw.get("command_id", "")),
                        str(raw.get("request_payload", "")),
                        str(raw.get("request_fingerprint", "")),
                        str(raw.get("runtime_intent_transaction_id", "")),
                        str(raw.get("runtime_intent_authority_hash", "")),
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
        payload_by_command: dict[tuple[OnlyBrokerCommandOperation, str], tuple[str, str]] = {}
        intent_by_order: dict[OnlyOrderId, tuple[str, str]] = {}
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
            command_id = item.command_id or f"SUBMIT:{item.order_id}"
            command_key = item.operation, command_id
            payload = item.request_payload, item.request_fingerprint
            prior_payload = payload_by_command.get(command_key)
            if prior_payload is None and item.request_payload:
                payload_by_command[command_key] = payload
            elif item.request_payload and prior_payload != payload:
                raise ValueError("BROKER_COMMAND_EVIDENCE_REQUEST_CONFLICT")
            intent = item.runtime_intent_transaction_id, item.runtime_intent_authority_hash
            prior_intent = intent_by_order.get(item.order_id)
            if item.runtime_intent_transaction_id and prior_intent is None:
                intent_by_order[item.order_id] = intent
            elif item.runtime_intent_transaction_id and prior_intent != intent:
                raise ValueError("BROKER_COMMAND_INTENT_REFERENCE_CONFLICT")


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
        self._unknown: set[str] = set()
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

    def mark_unknown(self, command_identity: OnlyOrderId | str) -> None:
        identity = f"SUBMIT:{command_identity}" if isinstance(command_identity, OnlyOrderId) else str(command_identity)
        self._unknown.add(identity)
        self._converged = False

    def resolve_unknown(self, command_identity: OnlyOrderId | str) -> None:
        identity = f"SUBMIT:{command_identity}" if isinstance(command_identity, OnlyOrderId) else str(command_identity)
        if identity not in self._unknown:
            raise RuntimeError("BROKER_UNKNOWN_RESOLUTION_UNPROVEN")
        self._unknown.remove(identity)

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
    def discover_order(
        self,
        order: OnlyOrderSnapshot,
        *,
        operation: OnlyBrokerCommandOperation,
    ) -> OnlyBrokerVenueDiscoveryResult: ...

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
        self._pending: dict[tuple[OnlyOrderId, OnlyBrokerCommandOperation], OnlyBrokerVenueDiscoveryResult] = {}

    def reconcile_unknown(
        self,
        order: OnlyOrderSnapshot,
        *,
        operation: OnlyBrokerCommandOperation = OnlyBrokerCommandOperation.SUBMIT,
    ) -> tuple[OnlyBrokerInboundUpdate, ...]:
        key = order.order_id, operation
        if key in self._pending:
            raise RuntimeError("BROKER_RECONCILIATION_FACTS_AWAITING_ACK")
        self._append(OnlyBrokerCommandEvidenceKind.RECONCILIATION_STARTED, order, operation=operation)
        result = self._discovery.discover_order(order, operation=operation)
        if result.order_id != order.order_id or result.operation is not operation:
            self._readiness.identity_conflict()
            raise ValueError("BROKER_RECONCILIATION_PROOF_SCOPE_CONFLICT")
        if result.presence is OnlyBrokerVenuePresence.INCONCLUSIVE:
            return ()
        if result.presence is OnlyBrokerVenuePresence.ABSENT_PROVEN:
            if operation is not OnlyBrokerCommandOperation.SUBMIT:
                return ()
            self._append(
                OnlyBrokerCommandEvidenceKind.NO_EXTERNAL_ORDER_PROVEN,
                order,
                operation=operation,
                detail_code=f"{result.proof_id}:{result.proof_fingerprint}",
            )
            self._resolve(order, operation=operation)
            return ()
        updates = result.discovered_facts
        if not updates:
            if self._discovery.verify_order(order):
                self._resolve(order, operation=operation)
            return ()
        for update in updates:
            update_order_id = getattr(update, "order_id", None)
            if update_order_id != order.order_id:
                self._readiness.identity_conflict()
                raise ValueError("BROKER_RECONCILIATION_ORDER_IDENTITY_CONFLICT")
            update_venue_order_id = getattr(update, "venue_order_id", None)
            fill = getattr(update, "fill", None)
            if update_venue_order_id is None and fill is not None:
                update_venue_order_id = getattr(fill, "venue_order_id", None)
            if (
                order.venue_order_id is not None
                and update_venue_order_id is not None
                and update_venue_order_id != order.venue_order_id
            ):
                self._readiness.identity_conflict()
                raise ValueError("BROKER_RECONCILIATION_VENUE_IDENTITY_CONFLICT")
            self._inbound.put(update)
        self._pending[key] = result
        return updates

    def acknowledge_unknown(
        self,
        order: OnlyOrderSnapshot,
        receipts: tuple[OnlyBrokerFactApplicationReceipt, ...],
        *,
        operation: OnlyBrokerCommandOperation = OnlyBrokerCommandOperation.SUBMIT,
    ) -> None:
        key = order.order_id, operation
        pending_result = self._pending.get(key)
        if pending_result is None:
            raise RuntimeError("BROKER_RECONCILIATION_ACK_WITHOUT_PENDING_PROOF")
        pending = pending_result.discovered_facts
        expected = tuple(update.update_id for update in pending)
        received = tuple(receipt.update_id for receipt in receipts)
        if len(set(received)) != len(received) or set(received) != set(expected):
            raise RuntimeError("BROKER_RECONCILIATION_ACK_SET_MISMATCH")
        if any(
            receipt.status not in {OnlyBrokerFactApplicationStatus.APPLIED, OnlyBrokerFactApplicationStatus.DUPLICATE}
            for receipt in receipts
        ):
            raise RuntimeError("BROKER_RECONCILIATION_FACT_NOT_DURABLY_APPLIED")
        if not self._discovery.verify_order(order):
            raise RuntimeError("BROKER_RECONCILIATION_CONVERGENCE_UNPROVEN")
        self._readiness.resolve_unknown(f"{operation.value}:{order.order_id}")
        venue_order_id = next(
            (
                value
                for update in pending
                for value in (
                    getattr(update, "venue_order_id", None),
                    getattr(getattr(update, "fill", None), "venue_order_id", None),
                )
                if isinstance(value, OnlyVenueOrderId)
            ),
            None,
        )
        self._append(
            OnlyBrokerCommandEvidenceKind.RESOLVED,
            order,
            venue_order_id,
            operation=operation,
        )
        del self._pending[key]

    def _resolve(
        self,
        order: OnlyOrderSnapshot,
        *,
        operation: OnlyBrokerCommandOperation,
    ) -> None:
        self._readiness.resolve_unknown(f"{operation.value}:{order.order_id}")
        self._append(OnlyBrokerCommandEvidenceKind.RESOLVED, order, operation=operation)

    def _append(
        self,
        kind: OnlyBrokerCommandEvidenceKind,
        order: OnlyOrderSnapshot,
        venue_order_id: OnlyVenueOrderId | None = None,
        *,
        operation: OnlyBrokerCommandOperation = OnlyBrokerCommandOperation.SUBMIT,
        detail_code: str = "",
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
                detail_code,
                operation=operation,
                command_id=f"{operation.value}:{order.order_id}",
            )
        )


__all__ = [name for name in globals() if name.startswith("Only")]
