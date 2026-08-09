"""Facts for durable Broker Order Accepted operations."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, fields

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyRuntimeId,
    OnlyVenueOrderId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.transaction.enums import OnlyRuntimeOperationKind

from .capability import ONLY_EXECUTION_SUPPORT_POLICY_VERSION, OnlyExecutionCapability


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyCommittedOrderAcceptedFactDraft(OnlyDomainModel):
    schema_version = 1

    operation_kind: OnlyRuntimeOperationKind
    accepted_identity: str
    accepted_payload_fingerprint: str
    broker_update_id: OnlyBrokerUpdateId
    runtime_id: OnlyRuntimeId
    gateway_id: OnlyBrokerGatewayId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    instrument_id: OnlyInstrumentId
    order_id: OnlyOrderId
    venue_order_id: OnlyVenueOrderId
    execution_capability: OnlyExecutionCapability
    execution_support_policy_version: str
    execution_support_fingerprint: str
    source_sequence: int
    processing_sequence: int
    correlation_id: str
    causation_id: str
    ts_event: OnlyTimestamp
    ts_init: OnlyTimestamp

    def __post_init__(self) -> None:
        if self.operation_kind is not OnlyRuntimeOperationKind.ORDER_ACCEPTED:
            raise ValueError("accepted fact requires ORDER_ACCEPTED operation kind")
        if (
            self.execution_capability is not OnlyExecutionCapability.DURABLE_ORDER_ACCEPTED
            or self.execution_support_policy_version != ONLY_EXECUTION_SUPPORT_POLICY_VERSION
            or len(self.execution_support_fingerprint) != 64
        ):
            raise ValueError("accepted fact requires a valid durable support proof")
        if not self.accepted_identity.startswith("EACK-") or len(self.accepted_payload_fingerprint) != 64:
            raise ValueError("accepted fact requires stable identity authority")
        if self.source_sequence < 0 or self.processing_sequence < 0 or self.ts_init < self.ts_event:
            raise ValueError("accepted fact sequence/timestamps are invalid")

    def finalize(
        self,
        execution_sequence: int,
        committed_at: OnlyTimestamp,
    ) -> OnlyCommittedOrderAcceptedFact:
        values = {item.name: getattr(self, item.name) for item in fields(self)}
        return OnlyCommittedOrderAcceptedFact(
            **values,
            execution_sequence=execution_sequence,
            ts_committed=committed_at,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyCommittedOrderAcceptedFact(OnlyDomainModel):
    schema_version = 1

    operation_kind: OnlyRuntimeOperationKind
    accepted_identity: str
    accepted_payload_fingerprint: str
    broker_update_id: OnlyBrokerUpdateId
    runtime_id: OnlyRuntimeId
    gateway_id: OnlyBrokerGatewayId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    instrument_id: OnlyInstrumentId
    order_id: OnlyOrderId
    venue_order_id: OnlyVenueOrderId
    execution_capability: OnlyExecutionCapability
    execution_support_policy_version: str
    execution_support_fingerprint: str
    source_sequence: int
    processing_sequence: int
    correlation_id: str
    causation_id: str
    ts_event: OnlyTimestamp
    ts_init: OnlyTimestamp
    execution_sequence: int
    ts_committed: OnlyTimestamp

    def __post_init__(self) -> None:
        draft_names = {item.name for item in fields(OnlyCommittedOrderAcceptedFactDraft)}
        OnlyCommittedOrderAcceptedFactDraft(**{name: getattr(self, name) for name in draft_names})
        if self.execution_sequence < 1 or self.ts_committed < self.ts_init:
            raise ValueError("committed accepted fact sequence/timestamp is invalid")

    @property
    def stable_order(self) -> tuple[int, int, int, str]:
        return self.execution_sequence, self.source_sequence, self.ts_event.unix_nanos, self.accepted_identity

    @property
    def stable_hash(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()


__all__ = ["OnlyCommittedOrderAcceptedFact", "OnlyCommittedOrderAcceptedFactDraft"]
