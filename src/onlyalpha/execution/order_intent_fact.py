"""Canonical durable local Order Intent facts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, fields

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyOrderId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.execution.execution_state import OnlyOrderExecutionState
from onlyalpha.transaction.enums import OnlyRuntimeOperationKind


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyOrderIntentFactDraft(OnlyDomainModel):
    schema_version = 1

    operation_kind: OnlyRuntimeOperationKind
    intent_identity: str
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    order_id: OnlyOrderId
    order: OnlyOrderExecutionState
    reservation_identities: tuple[str, ...]
    causal_reference: str
    ts_event: OnlyTimestamp
    prepared_at: OnlyTimestamp

    def __post_init__(self) -> None:
        if self.operation_kind is not OnlyRuntimeOperationKind.ORDER_INTENT:
            raise ValueError("Order Intent fact requires ORDER_INTENT operation kind")
        if not self.intent_identity.startswith("OINT-") or self.prepared_at < self.ts_event:
            raise ValueError("Order Intent fact identity/timestamps are invalid")
        if (
            self.order.runtime_id != self.runtime_id
            or self.order.account_id != self.account_id
            or self.order.cluster_id != self.cluster_id
            or self.order.order_id != self.order_id
        ):
            raise ValueError("Order Intent fact scope disagrees with canonical Order")
        if tuple(sorted(set(self.reservation_identities))) != self.reservation_identities:
            raise ValueError("Order Intent reservation identities must be unique canonical order")

    def finalize(self, execution_sequence: int, committed_at: OnlyTimestamp) -> OnlyCommittedOrderIntentFact:
        return OnlyCommittedOrderIntentFact(
            **{item.name: getattr(self, item.name) for item in fields(self)},
            execution_sequence=execution_sequence,
            ts_committed=committed_at,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyCommittedOrderIntentFact(OnlyDomainModel):
    schema_version = 1

    operation_kind: OnlyRuntimeOperationKind
    intent_identity: str
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    order_id: OnlyOrderId
    order: OnlyOrderExecutionState
    reservation_identities: tuple[str, ...]
    causal_reference: str
    ts_event: OnlyTimestamp
    prepared_at: OnlyTimestamp
    execution_sequence: int
    ts_committed: OnlyTimestamp

    def __post_init__(self) -> None:
        draft_names = {item.name for item in fields(OnlyOrderIntentFactDraft)}
        OnlyOrderIntentFactDraft(**{name: getattr(self, name) for name in draft_names})
        if self.execution_sequence < 1 or self.ts_committed < self.prepared_at:
            raise ValueError("Committed Order Intent sequence/timestamp is invalid")

    @property
    def stable_hash(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()


__all__ = ["OnlyCommittedOrderIntentFact", "OnlyOrderIntentFactDraft"]
