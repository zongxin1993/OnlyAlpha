"""Immutable facts stored by durable fee-reconciliation transactions."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.fee.evidence import OnlyExternalFeeEvidence
from onlyalpha.fee.reconciliation import OnlyFeeReconciliationDecision


@dataclass(frozen=True, slots=True)
class OnlyFeeReconciliationFactDraft(OnlyDomainModel):
    schema_version = 3

    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    evidence: OnlyExternalFeeEvidence
    decision: OnlyFeeReconciliationDecision
    ts_event: OnlyTimestamp

    def __post_init__(self) -> None:
        if self.evidence.account_id != self.account_id:
            raise ValueError("FEE_RECONCILIATION_ACCOUNT_SCOPE_CONFLICT")
        if self.decision.evidence_id != self.evidence.evidence_id:
            raise ValueError("FEE_RECONCILIATION_EVIDENCE_SCOPE_CONFLICT")

    def finalize(self, execution_sequence: int, committed_at: OnlyTimestamp) -> OnlyCommittedFeeReconciliationFact:
        return OnlyCommittedFeeReconciliationFact(
            self.runtime_id,
            self.account_id,
            self.evidence,
            self.decision,
            self.ts_event,
            execution_sequence,
            committed_at,
        )


@dataclass(frozen=True, slots=True)
class OnlyCommittedFeeReconciliationFact(OnlyDomainModel):
    schema_version = 3

    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    evidence: OnlyExternalFeeEvidence
    decision: OnlyFeeReconciliationDecision
    ts_event: OnlyTimestamp
    execution_sequence: int
    ts_committed: OnlyTimestamp

    def __post_init__(self) -> None:
        if self.execution_sequence < 1 or self.ts_committed < self.ts_event:
            raise ValueError("FEE_RECONCILIATION_COMMIT_BOUNDARY_INVALID")
        if self.evidence.account_id != self.account_id:
            raise ValueError("FEE_RECONCILIATION_ACCOUNT_SCOPE_CONFLICT")
        if self.decision.evidence_id != self.evidence.evidence_id:
            raise ValueError("FEE_RECONCILIATION_EVIDENCE_SCOPE_CONFLICT")


__all__ = ["OnlyCommittedFeeReconciliationFact", "OnlyFeeReconciliationFactDraft"]
