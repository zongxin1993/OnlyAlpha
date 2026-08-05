"""Operation-neutral durable Runtime transaction domain models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.event.model import OnlyEvent, OnlyEventType

from .enums import OnlyRuntimeOperationKind
from .facts import OnlyCommittedRuntimeFact, OnlyRuntimeFactDraft
from .projection import OnlyRuntimeProjection, OnlyRuntimeProjectionComponent, OnlyRuntimeProjectionOrder


@dataclass(frozen=True, slots=True)
class OnlyRuntimePrecondition(OnlyDomainModel):
    component: OnlyRuntimeProjectionComponent
    entity_key: str
    expected_version: int
    expected_state_hash: str

    def __post_init__(self) -> None:
        if not self.entity_key.strip() or self.expected_version < 0:
            raise ValueError("execution precondition requires entity and non-negative version")
        if len(self.expected_state_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.expected_state_hash
        ):
            raise ValueError("expected_state_hash must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class OnlyPreparedRuntimeTransaction:
    schema_version = 5

    transaction_id: str
    runtime_id: OnlyRuntimeId
    operation_kind: OnlyRuntimeOperationKind
    operation_identity: str
    account_id: OnlyAccountId | None
    effective_time: OnlyTimestamp
    prepared_at: OnlyTimestamp
    fact_draft: OnlyRuntimeFactDraft
    projections: tuple[OnlyRuntimeProjection, ...]
    outbox_events: tuple[OnlyEvent, ...]
    preconditions: tuple[OnlyRuntimePrecondition, ...]
    authority_hash: str = ""
    payload_hash: str = ""

    def __post_init__(self) -> None:
        if not self.transaction_id.strip() or not self.operation_identity.strip():
            raise ValueError("prepared Runtime transaction requires stable identities")
        scope = self.fact_draft
        if scope.runtime_id != self.runtime_id or (self.account_id is not None and scope.account_id != self.account_id):
            raise ValueError("prepared transaction and fact draft scopes disagree")
        self._validate_projections()
        self._validate_events()
        if self.prepared_at < self.effective_time or self.effective_time != self.fact_draft.ts_event:
            raise ValueError("prepared Runtime transaction effective/prepared times disagree")
        from onlyalpha.transaction.codec import (
            only_prepared_runtime_transaction_authority_hash,
            only_prepared_runtime_transaction_payload_hash,
        )

        authority_hash = only_prepared_runtime_transaction_authority_hash(self, verify=False)
        if not self.authority_hash:
            object.__setattr__(self, "authority_hash", authority_hash)
        elif self.authority_hash != authority_hash:
            raise ValueError("prepared execution transaction authority hash mismatch")
        payload_hash = only_prepared_runtime_transaction_payload_hash(self, verify=False)
        if not self.payload_hash:
            object.__setattr__(self, "payload_hash", payload_hash)
        elif self.payload_hash != payload_hash:
            raise ValueError("prepared execution transaction payload hash mismatch")

    def _validate_projections(self) -> None:
        from onlyalpha.transaction.codec import only_runtime_projection_payload_hash

        identities = tuple(item.identity for item in self.projections)
        if tuple(item.projection_sequence for item in identities) != tuple(range(1, len(identities) + 1)):
            raise ValueError("projection_sequence must be contiguous from one")
        orders = tuple(OnlyRuntimeProjectionOrder[item.component.name] for item in identities)
        if tuple(sorted(orders)) != orders:
            raise ValueError("execution projections violate the fixed component order")
        keys = tuple((item.component, item.entity_key) for item in identities)
        if len(keys) != len(set(keys)):
            raise ValueError("execution transaction contains duplicate component/entity projection")
        if any(item.identity.payload_hash != only_runtime_projection_payload_hash(item) for item in self.projections):
            raise ValueError("execution projection payload hash mismatch")
        projection_keys = tuple((item.component, item.entity_key) for item in identities)
        precondition_keys = tuple((item.component, item.entity_key) for item in self.preconditions)
        if precondition_keys != projection_keys or len(precondition_keys) != len(set(precondition_keys)):
            raise ValueError("preconditions must correspond one-to-one in projection order")
        if any(
            precondition.expected_version != projection.expected_version
            or precondition.expected_state_hash != projection.expected_state_hash
            for precondition, projection in zip(self.preconditions, identities, strict=True)
        ):
            raise ValueError("precondition and projection expected authority disagree")

    def _validate_events(self) -> None:
        from onlyalpha.transaction.event_identity import only_runtime_transaction_event_id

        event_ids = []
        for event_sequence, event in enumerate(self.outbox_events, start=1):
            if event.runtime_id != self.runtime_id or int(event.sequence) != event_sequence:
                raise ValueError("prepared transaction event scope/sequence mismatch")
            expected = only_runtime_transaction_event_id(
                transaction_id=self.transaction_id,
                event_sequence=event_sequence,
                event_type=cast(OnlyEventType, event.event_type),
            )
            if event.event_id != expected:
                raise ValueError("prepared transaction event identity is not deterministic")
            event.to_dict()
            event_ids.append(event.event_id)
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("prepared transaction contains duplicate event identity")


@dataclass(frozen=True, slots=True)
class OnlyCommittedRuntimeTransaction:
    schema_version = 5

    runtime_id: OnlyRuntimeId
    execution_sequence: int
    transaction_id: str
    operation_kind: OnlyRuntimeOperationKind
    operation_identity: str
    account_id: OnlyAccountId | None
    effective_time: OnlyTimestamp
    fact: OnlyCommittedRuntimeFact
    projections: tuple[OnlyRuntimeProjection, ...]
    outbox_events: tuple[OnlyEvent, ...]
    committed_at: OnlyTimestamp
    prepared_authority_hash: str
    prepared_payload_hash: str
    committed_payload_hash: str
    projection_ready: bool = False
    projected_at: OnlyTimestamp | None = None
    projection_error: str | None = None
    projection_failed_at: OnlyTimestamp | None = None

    def __post_init__(self) -> None:
        if (
            not self.transaction_id.strip()
            or not self.operation_identity.strip()
            or self.execution_sequence < 1
            or self.fact.execution_sequence != self.execution_sequence
        ):
            raise ValueError("committed transaction and fact sequence must agree and be positive")
        if (
            self.fact.runtime_id != self.runtime_id
            or self.fact.ts_committed != self.committed_at
            or (self.account_id is not None and self.fact.account_id != self.account_id)
        ):
            raise ValueError("committed transaction and fact scope/time disagree")
        if self.projection_ready and (self.projected_at is None or self.projection_error is not None):
            raise ValueError("projection-ready transaction requires projected_at and no error")
        if self.projection_ready and self.projection_failed_at is not None:
            raise ValueError("projection-ready transaction cannot retain failure time")
        if any(
            len(value) != 64 or any(character not in "0123456789abcdef" for character in value)
            for value in (
                self.prepared_authority_hash,
                self.prepared_payload_hash,
                self.committed_payload_hash,
            )
            if value
        ):
            raise ValueError("committed transaction hashes must be SHA-256 digests")


@dataclass(frozen=True, slots=True)
class OnlyStoredRuntimeTransaction:
    """Durable recovery record retaining the original planning contract."""

    prepared: OnlyPreparedRuntimeTransaction
    committed: OnlyCommittedRuntimeTransaction

    def __post_init__(self) -> None:
        if self.prepared.runtime_id != self.committed.runtime_id:
            raise ValueError("stored execution transaction Runtime scope disagrees")
        if self.prepared.transaction_id != self.committed.transaction_id:
            raise ValueError("stored execution transaction identity disagrees")
        if self.prepared.authority_hash != self.committed.prepared_authority_hash:
            raise ValueError("stored execution transaction authority hash disagrees")
        if self.prepared.payload_hash != self.committed.prepared_payload_hash:
            raise ValueError("stored execution transaction payload hash disagrees")


@dataclass(frozen=True, slots=True)
class OnlyRuntimeTransactionCommitResult:
    transaction: OnlyCommittedRuntimeTransaction
    inserted: bool


__all__ = [
    "OnlyCommittedRuntimeTransaction",
    "OnlyRuntimePrecondition",
    "OnlyRuntimeTransactionCommitResult",
    "OnlyPreparedRuntimeTransaction",
]
