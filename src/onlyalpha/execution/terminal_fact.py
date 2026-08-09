"""Minimal business facts for durable Order terminal operations."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, fields
from enum import StrEnum

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

from .capability import ONLY_EXECUTION_SUPPORT_POLICY_VERSION, OnlyExecutionCapability


class OnlyTerminalEconomicReleaseKind(StrEnum):
    CASH_RESERVATION = "CASH_RESERVATION"
    POSITION_RESERVATION = "POSITION_RESERVATION"


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyCommittedTerminalExecutionFactDraft(OnlyDomainModel):
    schema_version = 3

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
    execution_capability: OnlyExecutionCapability
    execution_support_policy_version: str
    execution_support_fingerprint: str
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
    economic_release_kind: OnlyTerminalEconomicReleaseKind
    reservation_released_quantity: OnlyQuantity | None
    reservation_released_cash: OnlyMoney | None
    risk_released_quantity: OnlyQuantity
    risk_released_notional: OnlyMoney | None
    active_order_count_delta: int
    cluster_active_order_count_delta: int

    def __post_init__(self) -> None:
        if self.operation_kind is not OnlyRuntimeOperationKind.ORDER_TERMINAL:
            raise ValueError("terminal fact requires ORDER_TERMINAL operation kind")
        if (
            self.execution_capability is not OnlyExecutionCapability.DURABLE_TERMINAL
            or self.execution_support_policy_version != ONLY_EXECUTION_SUPPORT_POLICY_VERSION
            or len(self.execution_support_fingerprint) != 64
        ):
            raise ValueError("terminal fact requires a valid durable support proof")
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
        if (
            min(
                self.filled_quantity_before.value,
                self.order_remaining_quantity.value,
                self.risk_released_quantity.value,
            )
            < 0
        ):
            raise ValueError("terminal fact quantities cannot be negative")
        cash_release = self.economic_release_kind is OnlyTerminalEconomicReleaseKind.CASH_RESERVATION
        if cash_release != (self.reservation_released_cash is not None):
            raise ValueError("terminal fact cash release shape is inconsistent")
        if cash_release == (self.reservation_released_quantity is not None):
            raise ValueError("terminal fact quantity release shape is inconsistent")
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
    schema_version = 3

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
    execution_capability: OnlyExecutionCapability
    execution_support_policy_version: str
    execution_support_fingerprint: str
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
    economic_release_kind: OnlyTerminalEconomicReleaseKind
    reservation_released_quantity: OnlyQuantity | None
    reservation_released_cash: OnlyMoney | None
    risk_released_quantity: OnlyQuantity
    risk_released_notional: OnlyMoney | None
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
    "OnlyTerminalEconomicReleaseKind",
]
