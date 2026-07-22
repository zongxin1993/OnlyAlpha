"""Immutable Execution Processor plans, results, audit and snapshots."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.account.models import OnlyAccountMutationResult, OnlyAccountSnapshot
from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyEngineId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyRuntimeId,
    OnlyTradeId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.event.model import OnlyEvent
from onlyalpha.execution.enums import (
    OnlyExecutionFailureCode,
    OnlyExecutionMutationStatus,
    OnlyExecutionMutationStep,
    OnlyExecutionProcessingStatus,
)
from onlyalpha.execution.scope import OnlyExecutionPositionScope
from onlyalpha.order.results import OnlyOrderMutationResult
from onlyalpha.position.enums import OnlyPositionMutationStatus
from onlyalpha.position.models import (
    OnlyPositionAllocationSnapshot,
    OnlyPositionMutationResult,
    OnlyPositionSnapshot,
)
from onlyalpha.risk.snapshots import OnlyRiskSnapshot
from onlyalpha.strategy_ledger.models import (
    OnlyStrategyLedgerMutationResult,
    OnlyStrategyLedgerSnapshot,
)


@dataclass(frozen=True, slots=True)
class OnlyExecutionProcessorConfig(OnlyDomainModel):
    engine_id: OnlyEngineId
    runtime_id: OnlyRuntimeId
    gateway_ids: tuple[OnlyBrokerGatewayId, ...]
    account_ids: tuple[OnlyAccountId, ...]

    def __post_init__(self) -> None:
        if not self.gateway_ids or not self.account_ids:
            raise ValueError("Execution Processor requires registered Gateway and Account scopes")
        object.__setattr__(self, "gateway_ids", tuple(sorted(set(self.gateway_ids), key=str)))
        object.__setattr__(self, "account_ids", tuple(sorted(set(self.account_ids), key=str)))


@dataclass(frozen=True, slots=True)
class OnlyExecutionProcessingContext(OnlyDomainModel):
    runtime_id: OnlyRuntimeId
    gateway_id: OnlyBrokerGatewayId
    account_id: OnlyAccountId
    update_id: OnlyBrokerUpdateId
    source_sequence: int
    processing_sequence: int
    ts_started: OnlyTimestamp


@dataclass(frozen=True, slots=True)
class OnlyExecutionFailure(OnlyDomainModel):
    code: OnlyExecutionFailureCode
    message: str
    failed_step: OnlyExecutionMutationStep
    exception_type: str | None = None


@dataclass(frozen=True, slots=True)
class OnlyExecutionMutationRecord(OnlyDomainModel):
    step: OnlyExecutionMutationStep
    status: OnlyExecutionMutationStatus
    summary: str


@dataclass(frozen=True, slots=True)
class OnlyExecutionMutationBundle(OnlyDomainModel):
    steps: tuple[OnlyExecutionMutationRecord, ...]
    order_mutation: OnlyOrderMutationResult | None = None
    position_mutation: OnlyPositionMutationResult | None = None
    allocation_mutation: OnlyPositionMutationStatus | None = None
    ledger_mutation: OnlyStrategyLedgerMutationResult | None = None
    account_mutation: OnlyAccountMutationResult | None = None
    reservation_mutations: tuple[str, ...] = ()
    risk_mutation: str | None = None


@dataclass(frozen=True, slots=True)
class OnlyExecutionInvariantViolation(OnlyDomainModel):
    code: str
    message: str
    blocking: bool = True


@dataclass(frozen=True, slots=True)
class OnlyExecutionInvariantResult(OnlyDomainModel):
    passed: bool
    violations: tuple[OnlyExecutionInvariantViolation, ...] = ()


@dataclass(frozen=True, slots=True)
class OnlyExecutionReconciliationRequest(OnlyDomainModel):
    request_id: str
    runtime_id: OnlyRuntimeId
    gateway_id: OnlyBrokerGatewayId
    account_id: OnlyAccountId
    update_id: OnlyBrokerUpdateId
    reason: str
    completed_steps: tuple[OnlyExecutionMutationStep, ...]
    failed_step: OnlyExecutionMutationStep
    order_id: OnlyOrderId | None = None
    trade_id: OnlyTradeId | None = None
    cluster_id: OnlyClusterId | None = None
    instrument_id: OnlyInstrumentId | None = None
    position_scope: OnlyExecutionPositionScope | None = None
    required_recovery: str = "QUERY_BROKER_AND_REPLAY_MISSING_FACTS"


@dataclass(frozen=True, slots=True)
class OnlyExecutionSnapshotBundle(OnlyDomainModel):
    processing_sequence: int
    as_of: OnlyTimestamp
    order: OnlyOrderSnapshot | None = None
    position: OnlyPositionSnapshot | None = None
    allocation: OnlyPositionAllocationSnapshot | None = None
    ledger: OnlyStrategyLedgerSnapshot | None = None
    account: OnlyAccountSnapshot | None = None
    risk: OnlyRiskSnapshot | None = None
    position_scope: OnlyExecutionPositionScope | None = None


@dataclass(frozen=True, slots=True)
class OnlyExecutionAuditRecord(OnlyDomainModel):
    audit_id: str
    runtime_id: OnlyRuntimeId
    gateway_id: OnlyBrokerGatewayId
    account_id: OnlyAccountId
    update_id: OnlyBrokerUpdateId
    update_type: str
    status: OnlyExecutionProcessingStatus
    processing_sequence: int
    completed_steps: tuple[OnlyExecutionMutationStep, ...]
    mutation_summary: tuple[str, ...]
    invariant_result: OnlyExecutionInvariantResult
    generated_event_types: tuple[str, ...]
    ts_started: OnlyTimestamp
    ts_completed: OnlyTimestamp
    failure: OnlyExecutionFailure | None = None
    reconciliation_request_id: str | None = None
    order_id: OnlyOrderId | None = None
    trade_id: OnlyTradeId | None = None
    cluster_id: OnlyClusterId | None = None
    instrument_id: OnlyInstrumentId | None = None
    position_scope: OnlyExecutionPositionScope | None = None


@dataclass(frozen=True, slots=True)
class OnlyExecutionProcessingResult(OnlyDomainModel):
    runtime_id: OnlyRuntimeId
    update_id: OnlyBrokerUpdateId
    update_type: str
    status: OnlyExecutionProcessingStatus
    sequence: int
    ts_started: OnlyTimestamp
    ts_completed: OnlyTimestamp
    mutation_bundle: OnlyExecutionMutationBundle
    snapshot_bundle: OnlyExecutionSnapshotBundle
    generated_events: tuple[OnlyEvent, ...]
    audit_record: OnlyExecutionAuditRecord
    failure: OnlyExecutionFailure | None = None
    reconciliation_request: OnlyExecutionReconciliationRequest | None = None
    quality_flags: tuple[str, ...] = ()

    @property
    def order_snapshot(self) -> OnlyOrderSnapshot | None:
        return self.snapshot_bundle.order

    @property
    def position_snapshot(self) -> OnlyPositionSnapshot | None:
        return self.snapshot_bundle.position

    @property
    def allocation_snapshot(self) -> OnlyPositionAllocationSnapshot | None:
        return self.snapshot_bundle.allocation

    @property
    def ledger_snapshot(self) -> OnlyStrategyLedgerSnapshot | None:
        return self.snapshot_bundle.ledger

    @property
    def account_snapshot(self) -> OnlyAccountSnapshot | None:
        return self.snapshot_bundle.account

    @property
    def risk_snapshot(self) -> OnlyRiskSnapshot | None:
        return self.snapshot_bundle.risk

    @property
    def allocation_status(self) -> OnlyPositionMutationStatus | None:
        return self.mutation_bundle.allocation_mutation

    @property
    def order(self) -> OnlyOrderMutationResult | None:
        return self.mutation_bundle.order_mutation

    @property
    def position(self) -> OnlyPositionMutationResult | None:
        return self.mutation_bundle.position_mutation

    @property
    def ledger(self) -> OnlyStrategyLedgerMutationResult | None:
        return self.mutation_bundle.ledger_mutation

    @property
    def account(self) -> OnlyAccountMutationResult | None:
        return self.mutation_bundle.account_mutation

    @property
    def final_ledger(self) -> OnlyStrategyLedgerSnapshot | None:
        return self.snapshot_bundle.ledger
