"""Durable Product commands and stable query projection over Strategy authorities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandId,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandReceipt,
    only_product_command_fingerprint,
)
from onlyalpha.strategy.errors import OnlyStrategyFreezeError, OnlyStrategyPromotionError
from onlyalpha.strategy.freeze import (
    OnlyStrategyFreezeOutcome,
    OnlyStrategyFreezeRequest,
)
from onlyalpha.strategy.promotion import (
    OnlyStrategyPromotionDecision,
    OnlyStrategyPromotionRecord,
    OnlyStrategyPromotionService,
    OnlyStrategyPromotionStage,
    _only_authorize_qualified_promotion,
    _OnlyQualifiedPromotionAuthorization,
)
from onlyalpha.strategy.qualification import (
    OnlyQualificationDecision,
    OnlyQualificationGate,
    OnlyQualificationOutcome,
    OnlyQualificationPolicyRevision,
)
from onlyalpha.strategy.revision import OnlyStrategyRevision
from onlyalpha.strategy.store import OnlyFrozenStrategyRevisionStore

if TYPE_CHECKING:
    from .strategy_authority import OnlyStrategyFreezeApplicationService


class OnlyStrategyFreezeAdmissionState(StrEnum):
    PREPARED = "PREPARED"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True, slots=True)
class OnlyStrategyFreezeCommandAdmission:
    command_id: OnlyProductCommandId
    command_fingerprint: str
    request: OnlyStrategyFreezeRequest
    state: OnlyStrategyFreezeAdmissionState
    prepared_at: datetime
    strategy_fingerprint: str | None = None
    freeze_relation_fingerprint: str | None = None
    completed_at: datetime | None = None


class OnlyStrategyProductStore(Protocol):
    def find_product_command_receipt(self, command_id: OnlyProductCommandId) -> OnlyProductCommandReceipt | None: ...

    def prepare_freeze_admission(
        self,
        command_id: OnlyProductCommandId,
        command_fingerprint: str,
        request: OnlyStrategyFreezeRequest,
        prepared_at: datetime,
    ) -> OnlyStrategyFreezeCommandAdmission: ...

    def load_freeze_admission(self, command_id: OnlyProductCommandId) -> OnlyStrategyFreezeCommandAdmission: ...

    def complete_freeze_admission(
        self,
        admission: OnlyStrategyFreezeCommandAdmission,
        outcome: OnlyStrategyFreezeOutcome,
        completed_at: datetime,
    ) -> OnlyProductCommandReceipt: ...

    def records(self, strategy_fingerprint: str) -> tuple[OnlyStrategyPromotionRecord, ...]: ...

    def append_promotion_with_receipt(
        self,
        record: OnlyStrategyPromotionRecord,
        command_id: OnlyProductCommandId,
        command_fingerprint: str,
        qualification_authorization: _OnlyQualifiedPromotionAuthorization,
    ) -> OnlyProductCommandReceipt: ...

    def load_promotion(self, record_fingerprint: str) -> OnlyStrategyPromotionRecord: ...


class _QualificationDecisionReader(Protocol):
    def load_verified(self, decision_fingerprint: str) -> OnlyQualificationDecision: ...


class _QualificationPolicyReader(Protocol):
    def load_exact(self, policy_id: str, policy_version: str) -> OnlyQualificationPolicyRevision: ...


@dataclass(frozen=True, slots=True)
class OnlyStrategyFreezeProductOutcome:
    freeze: OnlyStrategyFreezeOutcome
    replayed: bool


@dataclass(frozen=True, slots=True)
class OnlyStrategyProductView:
    revision: OnlyStrategyRevision
    freeze_relation_fingerprints: tuple[str, ...]
    current_stage: OnlyStrategyPromotionStage
    promotion_records: tuple[OnlyStrategyPromotionRecord, ...]


class OnlyStrategyFreezeProductService:
    def __init__(
        self,
        *,
        freeze: OnlyStrategyFreezeApplicationService,
        strategies: OnlyFrozenStrategyRevisionStore,
        store: OnlyStrategyProductStore,
        now_utc: Callable[[], datetime],
    ) -> None:
        self._freeze = freeze
        self._strategies = strategies
        self._store = store
        self._now_utc = now_utc

    def execute(
        self,
        command_id: OnlyProductCommandId,
        request: OnlyStrategyFreezeRequest,
    ) -> OnlyStrategyFreezeProductOutcome:
        fingerprint = only_product_command_fingerprint(
            {
                "research_run_id": request.research_run_id.value,
                "candidate_fingerprint": request.candidate_fingerprint,
                "actor": request.actor,
                "comment": request.comment,
            }
        )
        receipt = self._store.find_product_command_receipt(command_id)
        if receipt is not None:
            return self._replay(receipt, fingerprint)
        admission = self._store.prepare_freeze_admission(command_id, fingerprint, request, self._now_utc())
        if admission.command_fingerprint != fingerprint or admission.request != request:
            raise OnlyStrategyFreezeError("PRODUCT_COMMAND_CONFLICT", command_id.value)
        outcome = self._freeze.freeze(request)
        receipt = self._store.complete_freeze_admission(admission, outcome, self._now_utc())
        if receipt.outcome_ref.outcome_id != outcome.strategy_fingerprint:
            raise OnlyStrategyFreezeError("PRODUCT_COMMAND_RECEIPT_CORRUPT", command_id.value)
        return OnlyStrategyFreezeProductOutcome(outcome, admission.state is OnlyStrategyFreezeAdmissionState.COMPLETED)

    def _replay(self, receipt: OnlyProductCommandReceipt, fingerprint: str) -> OnlyStrategyFreezeProductOutcome:
        if (
            receipt.command_kind is not OnlyProductCommandKind.FREEZE_STRATEGY
            or receipt.outcome_ref.kind is not OnlyProductCommandOutcomeKind.STRATEGY
            or receipt.command_fingerprint != fingerprint
        ):
            raise OnlyStrategyFreezeError("PRODUCT_COMMAND_CONFLICT", receipt.command_id.value)
        strategy_fingerprint = receipt.outcome_ref.outcome_id
        self._strategies.load_verified(strategy_fingerprint)
        admission = self._store.load_freeze_admission(receipt.command_id)
        if (
            admission.state is not OnlyStrategyFreezeAdmissionState.COMPLETED
            or admission.strategy_fingerprint != strategy_fingerprint
            or admission.command_fingerprint != fingerprint
        ):
            raise OnlyStrategyFreezeError("PRODUCT_COMMAND_RECEIPT_CORRUPT", receipt.command_id.value)
        outcome = self._freeze.freeze(admission.request)
        if outcome.freeze_record.record_fingerprint != admission.freeze_relation_fingerprint:
            raise OnlyStrategyFreezeError("PRODUCT_COMMAND_RECEIPT_CORRUPT", receipt.command_id.value)
        return OnlyStrategyFreezeProductOutcome(outcome, True)


class _ReceiptPromotionLedger:
    def __init__(
        self,
        store: OnlyStrategyProductStore,
        command_id: OnlyProductCommandId,
        command_fingerprint: str,
        qualification_authorization: _OnlyQualifiedPromotionAuthorization,
    ) -> None:
        self._store = store
        self._command_id = command_id
        self._command_fingerprint = command_fingerprint
        self._qualification_authorization = qualification_authorization

    def records(self, strategy_fingerprint: str) -> tuple[OnlyStrategyPromotionRecord, ...]:
        return self._store.records(strategy_fingerprint)

    def append(self, record: OnlyStrategyPromotionRecord) -> OnlyStrategyPromotionRecord:
        receipt = self._store.append_promotion_with_receipt(
            record,
            self._command_id,
            self._command_fingerprint,
            self._qualification_authorization,
        )
        if receipt.outcome_ref.outcome_id == record.record_fingerprint:
            return record
        return self._store.load_promotion(receipt.outcome_ref.outcome_id)


class OnlyStrategyPromotionProductService:
    def __init__(
        self,
        *,
        strategies: OnlyFrozenStrategyRevisionStore,
        store: OnlyStrategyProductStore,
        qualification_decisions: _QualificationDecisionReader,
        qualification_policies: _QualificationPolicyReader,
        audit_time: Callable[[], datetime],
    ) -> None:
        self._strategies = strategies
        self._store = store
        self._qualification_decisions = qualification_decisions
        self._qualification_policies = qualification_policies
        self._audit_time = audit_time

    def promote_to_backtest(
        self,
        *,
        command_id: OnlyProductCommandId,
        strategy_fingerprint: str,
        qualification_decision_fingerprint: str,
        policy_fingerprint: str,
        reason: str,
        actor: str,
    ) -> tuple[OnlyStrategyPromotionRecord, bool]:
        return self._promote(
            command_id=command_id,
            strategy_fingerprint=strategy_fingerprint,
            to_stage=OnlyStrategyPromotionStage.BACKTEST,
            qualification_decision_fingerprint=qualification_decision_fingerprint,
            policy_fingerprint=policy_fingerprint,
            reason=reason,
            actor=actor,
        )

    def promote_to_sim(
        self,
        *,
        command_id: OnlyProductCommandId,
        strategy_fingerprint: str,
        qualification_decision_fingerprint: str,
        policy_fingerprint: str,
        reason: str,
        actor: str,
    ) -> tuple[OnlyStrategyPromotionRecord, bool]:
        return self._promote(
            command_id=command_id,
            strategy_fingerprint=strategy_fingerprint,
            to_stage=OnlyStrategyPromotionStage.SIM,
            qualification_decision_fingerprint=qualification_decision_fingerprint,
            policy_fingerprint=policy_fingerprint,
            reason=reason,
            actor=actor,
        )

    def _promote(
        self,
        *,
        command_id: OnlyProductCommandId,
        strategy_fingerprint: str,
        to_stage: OnlyStrategyPromotionStage,
        qualification_decision_fingerprint: str,
        policy_fingerprint: str,
        reason: str,
        actor: str,
    ) -> tuple[OnlyStrategyPromotionRecord, bool]:
        fingerprint = only_product_command_fingerprint(
            {
                "strategy_fingerprint": strategy_fingerprint,
                "to_stage": to_stage.value,
                "qualification_decision_fingerprint": qualification_decision_fingerprint,
                "policy_fingerprint": policy_fingerprint,
                "decision": OnlyStrategyPromotionDecision.APPROVED.value,
                "reason": reason,
                "actor": actor,
            }
        )
        receipt = self._store.find_product_command_receipt(command_id)
        if receipt is not None:
            if (
                receipt.command_kind is not OnlyProductCommandKind.PROMOTE_STRATEGY
                or receipt.outcome_ref.kind is not OnlyProductCommandOutcomeKind.STRATEGY_PROMOTION
                or receipt.command_fingerprint != fingerprint
            ):
                raise OnlyStrategyPromotionError("PRODUCT_COMMAND_CONFLICT", command_id.value)
            return self._store.load_promotion(receipt.outcome_ref.outcome_id), True
        decision = self._load_qualification(qualification_decision_fingerprint)
        expected_gate = (
            OnlyQualificationGate.RESEARCH_TO_BACKTEST
            if to_stage is OnlyStrategyPromotionStage.BACKTEST
            else OnlyQualificationGate.BACKTEST_TO_SIM
        )
        if decision.outcome is not OnlyQualificationOutcome.APPROVED:
            raise OnlyStrategyPromotionError("QUALIFICATION_DECISION_NOT_APPROVED", qualification_decision_fingerprint)
        if decision.subject_strategy_fingerprint != strategy_fingerprint:
            raise OnlyStrategyPromotionError(
                "QUALIFICATION_DECISION_SUBJECT_MISMATCH", qualification_decision_fingerprint
            )
        if decision.gate is not expected_gate:
            raise OnlyStrategyPromotionError("QUALIFICATION_EVIDENCE_GATE_MISMATCH", qualification_decision_fingerprint)
        if decision.policy_fingerprint != policy_fingerprint:
            raise OnlyStrategyPromotionError(
                "QUALIFICATION_DECISION_POLICY_MISMATCH", qualification_decision_fingerprint
            )
        try:
            policy = self._qualification_policies.load_exact(decision.policy_id, decision.policy_version)
        except Exception as exc:
            raise OnlyStrategyPromotionError("QUALIFICATION_POLICY_NOT_FOUND", decision.policy_fingerprint) from exc
        if policy.policy_fingerprint != policy_fingerprint or policy.gate is not expected_gate:
            raise OnlyStrategyPromotionError(
                "QUALIFICATION_DECISION_POLICY_MISMATCH", qualification_decision_fingerprint
            )
        evidence = {qualification_decision_fingerprint}
        if expected_gate is OnlyQualificationGate.RESEARCH_TO_BACKTEST:
            binding = decision.evidence[0].subject_binding_fingerprint
            relations = self._strategies.freeze_relations(strategy_fingerprint)
            if binding is None or binding not in {item.relation_fingerprint for item in relations}:
                raise OnlyStrategyPromotionError("STRATEGY_FREEZE_EVIDENCE_INVALID", str(binding))
            evidence.add(binding)
        qualification_authorization = _only_authorize_qualified_promotion(qualification_decision_fingerprint)
        ledger = _ReceiptPromotionLedger(
            self._store,
            command_id,
            fingerprint,
            qualification_authorization,
        )
        record = OnlyStrategyPromotionService(self._strategies, ledger, self._audit_time).record(
            strategy_fingerprint=strategy_fingerprint,
            to_stage=to_stage,
            evidence_fingerprints=tuple(sorted(evidence)),
            decision=OnlyStrategyPromotionDecision.APPROVED,
            reason=reason,
            actor=actor,
            qualification_authorization=qualification_authorization,
        )
        return record, False

    def _load_qualification(self, fingerprint: str) -> OnlyQualificationDecision:
        try:
            decision = self._qualification_decisions.load_verified(fingerprint)
        except Exception as exc:
            raise OnlyStrategyPromotionError("QUALIFICATION_DECISION_CORRUPT", fingerprint) from exc
        if decision.decision_fingerprint != fingerprint:
            raise OnlyStrategyPromotionError("QUALIFICATION_DECISION_CORRUPT", fingerprint)
        return decision


class OnlyStrategyQueryService:
    def __init__(self, strategies: OnlyFrozenStrategyRevisionStore, promotions: OnlyStrategyProductStore) -> None:
        self._strategies = strategies
        self._promotions = promotions

    def get(self, strategy_fingerprint: str) -> OnlyStrategyProductView:
        revision = self._strategies.load_verified(strategy_fingerprint)
        relations = self._strategies.freeze_relations(strategy_fingerprint)
        records = self._promotions.records(strategy_fingerprint)
        stage = self.current_stage(strategy_fingerprint)
        return OnlyStrategyProductView(
            revision,
            tuple(item.relation_fingerprint for item in relations),
            stage,
            records,
        )

    def current_stage(self, strategy_fingerprint: str) -> OnlyStrategyPromotionStage:
        """Read Promotion stage without exposing mutation capability to callers."""

        promotions = self._promotions

        class _QueryLedger:
            def records(_, value: str) -> tuple[OnlyStrategyPromotionRecord, ...]:
                return promotions.records(value)

            def append(_, record: OnlyStrategyPromotionRecord) -> OnlyStrategyPromotionRecord:
                raise RuntimeError("query must not produce Promotion facts")

        return OnlyStrategyPromotionService(
            self._strategies,
            _QueryLedger(),
            self._audit_time_unreachable,
        ).current_stage(strategy_fingerprint)

    @staticmethod
    def _audit_time_unreachable() -> datetime:
        raise RuntimeError("query must not produce Promotion facts")


__all__ = [name for name in globals() if name.startswith("Only")]
