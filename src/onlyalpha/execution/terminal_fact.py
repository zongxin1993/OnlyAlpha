"""Facts for durable Order terminal operations that create no Trade."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, fields

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyRuntimeId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyMoney, OnlyQuantity
from onlyalpha.risk.enums import OnlyRiskReleaseReason
from onlyalpha.transaction.enums import OnlyRuntimeOperationKind


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyCommittedTerminalExecutionFactDraft(OnlyDomainModel):
    schema_version = 1

    operation_kind: OnlyRuntimeOperationKind
    terminal_identity: str
    terminal_payload_fingerprint: str
    broker_update_id: OnlyBrokerUpdateId
    runtime_id: OnlyRuntimeId
    gateway_id: OnlyBrokerGatewayId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    instrument_id: OnlyInstrumentId
    order_id: OnlyOrderId
    source_sequence: int
    processing_sequence: int
    correlation_id: str
    causation_id: str
    ts_event: OnlyTimestamp
    ts_init: OnlyTimestamp
    terminal_status: OnlyOrderStatus
    terminal_reason: str
    risk_release_reason: OnlyRiskReleaseReason
    filled_quantity_before: OnlyQuantity
    order_remaining_quantity: OnlyQuantity
    position_reservation_consumed_before: OnlyQuantity
    position_reservation_released_delta: OnlyQuantity
    position_reservation_remaining_after: OnlyQuantity
    risk_reservation_consumed_quantity_before: OnlyQuantity
    risk_reservation_released_quantity_delta: OnlyQuantity
    risk_reservation_released_notional_delta: OnlyMoney | None
    risk_reservation_remaining_quantity_after: OnlyQuantity
    active_order_count_delta: int
    cluster_active_order_count_delta: int

    def __post_init__(self) -> None:
        if self.operation_kind is not OnlyRuntimeOperationKind.ORDER_TERMINAL:
            raise ValueError("terminal fact requires ORDER_TERMINAL operation kind")
        if not self.terminal_identity.startswith("ETERM-") or len(self.terminal_payload_fingerprint) != 64:
            raise ValueError("terminal fact requires stable identity authority")
        if self.terminal_status not in {
            OnlyOrderStatus.CANCELLED,
            OnlyOrderStatus.REJECTED,
            OnlyOrderStatus.EXPIRED,
        }:
            raise ValueError("terminal fact status is unsupported")
        if self.source_sequence < 0 or self.processing_sequence < 0 or self.ts_init < self.ts_event:
            raise ValueError("terminal fact sequence/timestamps are invalid")
        quantities = (
            self.filled_quantity_before,
            self.order_remaining_quantity,
            self.position_reservation_consumed_before,
            self.position_reservation_released_delta,
            self.position_reservation_remaining_after,
            self.risk_reservation_consumed_quantity_before,
            self.risk_reservation_released_quantity_delta,
            self.risk_reservation_remaining_quantity_after,
        )
        if any(item.value < 0 for item in quantities):
            raise ValueError("terminal fact quantities cannot be negative")
        if self.position_reservation_remaining_after.value != 0:
            raise ValueError("terminal fact must release the remaining Position Reservation")
        if self.risk_reservation_remaining_quantity_after.value != 0:
            raise ValueError("terminal fact must release the remaining Risk Reservation")
        if self.active_order_count_delta != -1 or self.cluster_active_order_count_delta != -1:
            raise ValueError("terminal fact must close exactly one active Order")

    def finalize(
        self,
        execution_sequence: int,
        committed_at: OnlyTimestamp,
    ) -> OnlyCommittedTerminalExecutionFact:
        values = {item.name: getattr(self, item.name) for item in fields(self)}
        return OnlyCommittedTerminalExecutionFact(
            **values,
            execution_sequence=execution_sequence,
            ts_committed=committed_at,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyCommittedTerminalExecutionFact(OnlyDomainModel):
    schema_version = 1

    operation_kind: OnlyRuntimeOperationKind
    terminal_identity: str
    terminal_payload_fingerprint: str
    broker_update_id: OnlyBrokerUpdateId
    runtime_id: OnlyRuntimeId
    gateway_id: OnlyBrokerGatewayId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    instrument_id: OnlyInstrumentId
    order_id: OnlyOrderId
    source_sequence: int
    processing_sequence: int
    correlation_id: str
    causation_id: str
    ts_event: OnlyTimestamp
    ts_init: OnlyTimestamp
    terminal_status: OnlyOrderStatus
    terminal_reason: str
    risk_release_reason: OnlyRiskReleaseReason
    filled_quantity_before: OnlyQuantity
    order_remaining_quantity: OnlyQuantity
    position_reservation_consumed_before: OnlyQuantity
    position_reservation_released_delta: OnlyQuantity
    position_reservation_remaining_after: OnlyQuantity
    risk_reservation_consumed_quantity_before: OnlyQuantity
    risk_reservation_released_quantity_delta: OnlyQuantity
    risk_reservation_released_notional_delta: OnlyMoney | None
    risk_reservation_remaining_quantity_after: OnlyQuantity
    active_order_count_delta: int
    cluster_active_order_count_delta: int
    execution_sequence: int
    ts_committed: OnlyTimestamp

    def __post_init__(self) -> None:
        draft_names = {item.name for item in fields(OnlyCommittedTerminalExecutionFactDraft)}
        OnlyCommittedTerminalExecutionFactDraft(**{name: getattr(self, name) for name in draft_names})
        if self.execution_sequence < 1 or self.ts_committed < self.ts_init:
            raise ValueError("committed terminal fact sequence/timestamp is invalid")

    @property
    def stable_order(self) -> tuple[int, int, int, str]:
        return self.execution_sequence, self.source_sequence, self.ts_event.unix_nanos, self.terminal_identity

    @property
    def stable_hash(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()


__all__ = [
    "OnlyCommittedTerminalExecutionFact",
    "OnlyCommittedTerminalExecutionFactDraft",
]
