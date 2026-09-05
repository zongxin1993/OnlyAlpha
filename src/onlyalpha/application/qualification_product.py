"""Idempotent Product command/query boundary for Strategy Qualification."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandId,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandReceipt,
    only_product_command_fingerprint,
)
from onlyalpha.strategy.errors import OnlyQualificationError
from onlyalpha.strategy.qualification import (
    OnlyQualificationDecision,
    OnlyQualificationEvaluator,
    OnlyQualificationEvidenceReference,
    OnlyQualificationPolicyRevision,
)


class OnlyQualificationAdmissionState(StrEnum):
    PREPARED = "PREPARED"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True, slots=True)
class OnlyQualificationCommandAdmission:
    command_id: OnlyProductCommandId
    command_fingerprint: str
    subject_strategy_fingerprint: str
    policy_id: str
    policy_version: str
    evidence: tuple[OnlyQualificationEvidenceReference, ...]
    state: OnlyQualificationAdmissionState
    prepared_at: datetime
    decision_fingerprint: str | None = None
    completed_at: datetime | None = None


class OnlyQualificationProductStore(Protocol):
    def find_product_command_receipt(self, command_id: OnlyProductCommandId) -> OnlyProductCommandReceipt | None: ...

    def prepare_qualification_admission(
        self, admission: OnlyQualificationCommandAdmission
    ) -> OnlyQualificationCommandAdmission: ...

    def load_qualification_admission(self, command_id: OnlyProductCommandId) -> OnlyQualificationCommandAdmission: ...

    def complete_qualification_admission(
        self,
        admission: OnlyQualificationCommandAdmission,
        decision: OnlyQualificationDecision,
        completed_at: datetime,
    ) -> OnlyProductCommandReceipt: ...


class _DecisionReader(Protocol):
    def load_verified(self, decision_fingerprint: str) -> OnlyQualificationDecision: ...

    def decisions_for_subject(self, strategy_fingerprint: str) -> tuple[OnlyQualificationDecision, ...]: ...


class _PolicyReader(Protocol):
    def load_exact(self, policy_id: str, policy_version: str) -> OnlyQualificationPolicyRevision: ...

    def policies(self) -> tuple[OnlyQualificationPolicyRevision, ...]: ...


@dataclass(frozen=True, slots=True)
class OnlyQualificationProductOutcome:
    decision: OnlyQualificationDecision
    replayed: bool


class OnlyQualificationProductService:
    def __init__(
        self,
        *,
        evaluator: OnlyQualificationEvaluator,
        decisions: _DecisionReader,
        store: OnlyQualificationProductStore,
        now_utc: Callable[[], datetime],
    ) -> None:
        self._evaluator = evaluator
        self._decisions = decisions
        self._store = store
        self._now_utc = now_utc

    def evaluate(
        self,
        *,
        command_id: OnlyProductCommandId,
        subject_strategy_fingerprint: str,
        policy_id: str,
        policy_version: str,
        evidence: tuple[OnlyQualificationEvidenceReference, ...],
    ) -> OnlyQualificationProductOutcome:
        command_fingerprint = only_product_command_fingerprint(
            {
                "subject_strategy_fingerprint": subject_strategy_fingerprint,
                "policy_id": policy_id,
                "policy_version": policy_version,
                "evidence": [item.to_dict() for item in evidence],
            }
        )
        receipt = self._store.find_product_command_receipt(command_id)
        if receipt is not None:
            return OnlyQualificationProductOutcome(
                self._replay_receipt(receipt, command_fingerprint),
                True,
            )
        prepared = OnlyQualificationCommandAdmission(
            command_id,
            command_fingerprint,
            subject_strategy_fingerprint,
            policy_id,
            policy_version,
            evidence,
            OnlyQualificationAdmissionState.PREPARED,
            self._now_utc(),
        )
        admission = self._store.prepare_qualification_admission(prepared)
        if (
            admission.command_fingerprint != command_fingerprint
            or admission.subject_strategy_fingerprint != subject_strategy_fingerprint
            or admission.policy_id != policy_id
            or admission.policy_version != policy_version
            or admission.evidence != evidence
        ):
            raise OnlyQualificationError("PRODUCT_COMMAND_CONFLICT", command_id.value)
        if admission.state is OnlyQualificationAdmissionState.COMPLETED:
            if admission.decision_fingerprint is None:
                raise OnlyQualificationError("PRODUCT_COMMAND_RECEIPT_CORRUPT", command_id.value)
            return OnlyQualificationProductOutcome(
                self._decisions.load_verified(admission.decision_fingerprint),
                True,
            )
        decision = self._evaluator.evaluate(
            subject_strategy_fingerprint=subject_strategy_fingerprint,
            policy_id=policy_id,
            policy_version=policy_version,
            evidence=evidence,
        )
        receipt = self._store.complete_qualification_admission(
            admission,
            decision,
            self._now_utc(),
        )
        if receipt.outcome_ref.outcome_id != decision.decision_fingerprint:
            raise OnlyQualificationError("PRODUCT_COMMAND_RECEIPT_CORRUPT", command_id.value)
        return OnlyQualificationProductOutcome(decision, False)

    def _replay_receipt(
        self, receipt: OnlyProductCommandReceipt, command_fingerprint: str
    ) -> OnlyQualificationDecision:
        if (
            receipt.command_kind is not OnlyProductCommandKind.EVALUATE_QUALIFICATION
            or receipt.outcome_ref.kind is not OnlyProductCommandOutcomeKind.QUALIFICATION_DECISION
            or receipt.command_fingerprint != command_fingerprint
        ):
            raise OnlyQualificationError("PRODUCT_COMMAND_CONFLICT", receipt.command_id.value)
        admission = self._store.load_qualification_admission(receipt.command_id)
        if (
            admission.state is not OnlyQualificationAdmissionState.COMPLETED
            or admission.command_fingerprint != command_fingerprint
            or admission.decision_fingerprint != receipt.outcome_ref.outcome_id
        ):
            raise OnlyQualificationError("PRODUCT_COMMAND_RECEIPT_CORRUPT", receipt.command_id.value)
        return self._decisions.load_verified(receipt.outcome_ref.outcome_id)


class OnlyQualificationQueryService:
    def __init__(self, policies: _PolicyReader, decisions: _DecisionReader) -> None:
        self._policies = policies
        self._decisions = decisions

    def policy(self, policy_id: str, policy_version: str) -> OnlyQualificationPolicyRevision:
        return self._policies.load_exact(policy_id, policy_version)

    def policies(self) -> tuple[OnlyQualificationPolicyRevision, ...]:
        return self._policies.policies()

    def decision(self, decision_fingerprint: str) -> OnlyQualificationDecision:
        return self._decisions.load_verified(decision_fingerprint)

    def decisions_for_subject(self, strategy_fingerprint: str) -> tuple[OnlyQualificationDecision, ...]:
        return self._decisions.decisions_for_subject(strategy_fingerprint)


__all__ = [name for name in globals() if name.startswith("Only")]
