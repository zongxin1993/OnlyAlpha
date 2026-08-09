"""Append-only evidence lineage, decisions, and component adjustment authority."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import OnlyAccountId
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.fee.adjustment import OnlyFeeAdjustment, OnlyFeeAdjustmentDirection, OnlyUnallocatedExternalFeeState
from onlyalpha.fee.evidence import OnlyExternalFeeEvidence
from onlyalpha.fee.reconciliation import OnlyFeeReconciliationDecision, OnlyPriorFeeAdjustment


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
    schema_version = 2

    def __init__(self) -> None:
        self._evidence: dict[str, OnlyExternalFeeEvidenceState] = {}
        self._evidence_versions: dict[tuple[str, int], str] = {}
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
        family = evidence.family_identity.fingerprint
        current_id = self._evidence_versions.get((family, evidence.revision_sequence))
        if current_id is not None:
            current = self._evidence[current_id].evidence
            return (
                "DUPLICATE_EVIDENCE"
                if current.content_fingerprint == evidence.content_fingerprint
                else "EXTERNAL_FEE_EVIDENCE_IDENTITY_CONFLICT"
            )
        family_items = sorted(
            (
                state.evidence
                for state in self._evidence.values()
                if state.identity_authority and state.evidence.family_identity.fingerprint == family
            ),
            key=lambda item: item.revision_sequence,
        )
        if not family_items:
            return (
                None
                if evidence.revision_sequence == 1 and evidence.supersedes_evidence_id is None
                else "EXTERNAL_FEE_EVIDENCE_IDENTITY_CONFLICT"
            )
        latest = family_items[-1]
        if (
            evidence.revision_sequence != latest.revision_sequence + 1
            or evidence.supersedes_evidence_id != latest.evidence_id
        ):
            return "EXTERNAL_FEE_EVIDENCE_IDENTITY_CONFLICT"
        return None

    def prior_adjustments(self, evidence: OnlyExternalFeeEvidence) -> tuple[OnlyPriorFeeAdjustment, ...]:
        result = []
        for state in self._adjustments.values():
            item = state.adjustment
            if item.account_id != evidence.account_id or item.scope.fingerprint != evidence.scope.fingerprint:
                continue
            if item.amount.currency != evidence.currency:
                raise ValueError("FEE_RECONCILIATION_ADJUSTMENT_CURRENCY_CONFLICT")
            increases_component = (
                item.component_identity.economic_direction.value == "CHARGE"
                and item.direction is OnlyFeeAdjustmentDirection.SUPPLEMENTAL_CHARGE
            ) or (
                item.component_identity.economic_direction.value == "REBATE"
                and item.direction is OnlyFeeAdjustmentDirection.REFUND
            )
            signed = item.amount.amount if increases_component else -item.amount.amount
            result.append(
                OnlyPriorFeeAdjustment(
                    item.adjustment_id,
                    item.component_identity,
                    OnlyMoney(signed, item.amount.currency),
                )
            )
        return tuple(sorted(result, key=lambda item: item.adjustment_id))

    def restore_evidence(self, state: OnlyExternalFeeEvidenceState) -> None:
        current = self._evidence.get(state.evidence.evidence_id)
        if current is not None and current != state:
            raise ValueError("EXTERNAL_FEE_EVIDENCE_IDENTITY_CONFLICT")
        classification = self.classify(state.evidence)
        if state.identity_authority and classification not in {None, "DUPLICATE_EVIDENCE"}:
            raise ValueError(classification)
        self._evidence[state.evidence.evidence_id] = state
        if state.identity_authority:
            self._evidence_versions[(state.evidence.family_identity.fingerprint, state.evidence.revision_sequence)] = (
                state.evidence.evidence_id
            )

    def restore_decision(self, state: OnlyFeeReconciliationDecisionState) -> None:
        current = self._decisions.get(state.decision.reconciliation_id)
        if current is not None and current != state:
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
        self._evidence_versions = {}
        self._decisions = {}
        self._adjustments = {}
        self._unallocated = {}
        for item in sorted(
            evidence, key=lambda value: (value.evidence.family_identity.fingerprint, value.evidence.revision_sequence)
        ):
            self.restore_evidence(item)
        for decision_state in decisions:
            self.restore_decision(decision_state)
        for adjustment_state in adjustments:
            self.restore_adjustment(adjustment_state)
        for unallocated_state in unallocated:
            self.restore_unallocated(unallocated_state)


__all__ = [name for name in globals() if name.startswith("Only")]
