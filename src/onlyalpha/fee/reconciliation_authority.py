"""Versioned authorities installed only by durable fee-reconciliation projections."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import OnlyAccountId
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.fee.adjustment import (
    OnlyFeeAdjustment,
    OnlyFeeAdjustmentDirection,
    OnlyUnallocatedExternalFeeState,
)
from onlyalpha.fee.evidence import OnlyExternalFeeEvidence
from onlyalpha.fee.reconciliation import OnlyFeeReconciliationDecision


@dataclass(frozen=True, slots=True)
class OnlyExternalFeeEvidenceState(OnlyDomainModel):
    evidence: OnlyExternalFeeEvidence
    identity_authority: bool
    version: int

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("external fee evidence version must be positive")


@dataclass(frozen=True, slots=True)
class OnlyFeeReconciliationDecisionState(OnlyDomainModel):
    decision: OnlyFeeReconciliationDecision
    version: int

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("fee reconciliation decision version must be positive")


@dataclass(frozen=True, slots=True)
class OnlyFeeAdjustmentState(OnlyDomainModel):
    adjustment: OnlyFeeAdjustment
    version: int

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("fee adjustment version must be positive")


class OnlyFeeReconciliationAuthority:
    """Append-only evidence, decision, adjustment, and unallocated authorities."""

    schema_version = 1

    def __init__(self) -> None:
        self._evidence: dict[str, OnlyExternalFeeEvidenceState] = {}
        self._evidence_identity: dict[tuple[str, OnlyAccountId, str, str], str] = {}
        self._decisions: dict[str, OnlyFeeReconciliationDecisionState] = {}
        self._adjustments: dict[str, OnlyFeeAdjustmentState] = {}
        self._unallocated: dict[OnlyAccountId, OnlyUnallocatedExternalFeeState] = {}

    def evidence(self, evidence_id: str) -> OnlyExternalFeeEvidenceState | None:
        return self._evidence.get(evidence_id)

    def decision(self, reconciliation_id: str) -> OnlyFeeReconciliationDecisionState | None:
        return self._decisions.get(reconciliation_id)

    def adjustment(self, adjustment_id: str) -> OnlyFeeAdjustmentState | None:
        return self._adjustments.get(adjustment_id)

    def unallocated(self, account_id: OnlyAccountId) -> OnlyUnallocatedExternalFeeState | None:
        return self._unallocated.get(account_id)

    def classify(self, evidence: OnlyExternalFeeEvidence) -> str | None:
        key = (evidence.broker_id, evidence.account_id, evidence.external_reference, evidence.report_version)
        fingerprint = self._evidence_identity.get(key)
        if fingerprint is None:
            return None
        return (
            "DUPLICATE_EVIDENCE"
            if fingerprint == evidence.content_fingerprint
            else "EXTERNAL_FEE_EVIDENCE_IDENTITY_CONFLICT"
        )

    def prior_adjustments(self, evidence: OnlyExternalFeeEvidence) -> OnlyMoney:
        currency = (
            evidence.reported_total.currency
            if evidence.reported_total is not None
            else evidence.reported_components[0].amount.currency
        )
        signed = Decimal(0)
        for state in self._adjustments.values():
            item = state.adjustment
            same_scope = (
                (evidence.trade_id is not None and item.trade_id == evidence.trade_id)
                or (evidence.order_id is not None and item.order_id == evidence.order_id)
                or (
                    evidence.statement_scope is not None
                    and item.statement_scope == evidence.statement_scope
                    and item.account_id == evidence.account_id
                )
            )
            if same_scope:
                if item.amount.currency != currency:
                    raise ValueError("FEE_RECONCILIATION_ADJUSTMENT_CURRENCY_CONFLICT")
                signed += (
                    item.amount.amount
                    if item.direction is OnlyFeeAdjustmentDirection.SUPPLEMENTAL_CHARGE
                    else -item.amount.amount
                )
        return OnlyMoney(signed, currency)

    def restore_evidence(self, state: OnlyExternalFeeEvidenceState) -> None:
        current = self._evidence.get(state.evidence.evidence_id)
        if current is not None and (current.evidence != state.evidence or state.version < current.version):
            raise ValueError("EXTERNAL_FEE_EVIDENCE_IDENTITY_CONFLICT")
        key = (
            state.evidence.broker_id,
            state.evidence.account_id,
            state.evidence.external_reference,
            state.evidence.report_version,
        )
        self._evidence[state.evidence.evidence_id] = state
        current_identity = self._evidence_identity.get(key)
        if state.identity_authority:
            if current_identity is not None and current_identity != state.evidence.content_fingerprint:
                raise ValueError("EXTERNAL_FEE_EVIDENCE_IDENTITY_CONFLICT")
            self._evidence_identity[key] = state.evidence.content_fingerprint

    def restore_decision(self, state: OnlyFeeReconciliationDecisionState) -> None:
        current = self._decisions.get(state.decision.reconciliation_id)
        if current is not None and (current.decision != state.decision or state.version < current.version):
            raise ValueError("FEE_RECONCILIATION_DECISION_CONFLICT")
        self._decisions[state.decision.reconciliation_id] = state

    def restore_adjustment(self, state: OnlyFeeAdjustmentState) -> None:
        current = self._adjustments.get(state.adjustment.adjustment_id)
        if current is not None and current != state:
            raise ValueError("FEE_ADJUSTMENT_IDENTITY_CONFLICT")
        self._adjustments[state.adjustment.adjustment_id] = state

    def restore_unallocated(self, state: OnlyUnallocatedExternalFeeState) -> None:
        current = self._unallocated.get(state.account_id)
        if current is not None and state.version < current.version:
            raise ValueError("unallocated external fee version cannot regress")
        self._unallocated[state.account_id] = state

    def capture_checkpoint(self) -> object:
        return {
            "schema_version": self.schema_version,
            "evidence": [self._evidence[key].to_json() for key in sorted(self._evidence)],
            "decisions": [self._decisions[key].to_json() for key in sorted(self._decisions)],
            "adjustments": [self._adjustments[key].to_json() for key in sorted(self._adjustments)],
            "unallocated": [self._unallocated[key].to_json() for key in sorted(self._unallocated, key=str)],
        }

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, dict) or payload.get("schema_version") != self.schema_version:
            raise ValueError("UNSUPPORTED_FEE_CHECKPOINT_SCHEMA")
        try:
            evidence = tuple(OnlyExternalFeeEvidenceState.from_json(str(item)) for item in payload["evidence"])
            decisions = tuple(OnlyFeeReconciliationDecisionState.from_json(str(item)) for item in payload["decisions"])
            adjustments = tuple(OnlyFeeAdjustmentState.from_json(str(item)) for item in payload["adjustments"])
            unallocated = tuple(OnlyUnallocatedExternalFeeState.from_json(str(item)) for item in payload["unallocated"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("fee reconciliation checkpoint is invalid") from exc
        self._evidence = {}
        self._evidence_identity = {}
        self._decisions = {}
        self._adjustments = {}
        self._unallocated = {}
        for evidence_state in sorted(
            evidence,
            key=lambda item: (item.evidence.received_at.unix_nanos, item.evidence.evidence_id),
        ):
            self.restore_evidence(evidence_state)
        for decision_state in decisions:
            self.restore_decision(decision_state)
        for adjustment_state in adjustments:
            self.restore_adjustment(adjustment_state)
        for unallocated_state in unallocated:
            self.restore_unallocated(unallocated_state)
        identity_keys = {
            (
                state.evidence.broker_id,
                state.evidence.account_id,
                state.evidence.external_reference,
                state.evidence.report_version,
            )
            for state in self._evidence.values()
        }
        if identity_keys != set(self._evidence_identity):
            raise ValueError("fee reconciliation checkpoint lacks evidence identity authority")


__all__ = [name for name in globals() if name.startswith("Only")]
