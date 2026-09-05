from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandId,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandOutcomeRef,
    OnlyProductCommandReceipt,
)
from onlyalpha.application.qualification_product import (
    OnlyQualificationAdmissionState,
    OnlyQualificationCommandAdmission,
    OnlyQualificationProductService,
)
from onlyalpha.application.strategy_product import OnlyStrategyPromotionProductService
from onlyalpha.strategy import OnlyFrozenStrategyRevisionStore, OnlyQualificationError, OnlyStrategyPromotionError
from onlyalpha.strategy.promotion import (
    OnlyInMemoryStrategyPromotionLedger,
    OnlyStrategyPromotionRecord,
    OnlyStrategyPromotionStage,
)
from onlyalpha.strategy.qualification import (
    OnlyQualificationCriterion,
    OnlyQualificationCriterionOutcome,
    OnlyQualificationCriterionResult,
    OnlyQualificationDecision,
    OnlyQualificationEvidenceKind,
    OnlyQualificationEvidenceReference,
    OnlyQualificationGate,
    OnlyQualificationOutcome,
    OnlyQualificationPolicyRevision,
    _only_authorize_qualification_decision_publication,
)
from onlyalpha.strategy.qualification_store import (
    OnlyQualificationPolicyStore,
    _only_compose_qualification_decision_authority,
    _OnlyQualificationDecisionPublisher,
)
from tests.strategy.p9_support import p9_strategy_case, publish_frozen_strategy_for_execution_test

NOW = datetime(2026, 9, 5, tzinfo=UTC)


class _ProductStore:
    def __init__(self) -> None:
        self.receipts: dict[str, OnlyProductCommandReceipt] = {}
        self.admissions: dict[str, OnlyQualificationCommandAdmission] = {}
        self.ledger = OnlyInMemoryStrategyPromotionLedger()
        self.promotions: dict[str, OnlyStrategyPromotionRecord] = {}

    def find_product_command_receipt(self, command_id):  # type: ignore[no-untyped-def]
        return self.receipts.get(command_id.value)

    def prepare_qualification_admission(self, admission):  # type: ignore[no-untyped-def]
        existing = self.admissions.get(admission.command_id.value)
        if existing is not None:
            return existing
        self.admissions[admission.command_id.value] = admission
        return admission

    def load_qualification_admission(self, command_id):  # type: ignore[no-untyped-def]
        return self.admissions[command_id.value]

    def complete_qualification_admission(self, admission, decision, completed_at):  # type: ignore[no-untyped-def]
        completed = replace(
            admission,
            state=OnlyQualificationAdmissionState.COMPLETED,
            decision_fingerprint=decision.decision_fingerprint,
            completed_at=completed_at,
        )
        self.admissions[admission.command_id.value] = completed
        receipt = OnlyProductCommandReceipt(
            admission.command_id,
            OnlyProductCommandKind.EVALUATE_QUALIFICATION,
            admission.command_fingerprint,
            OnlyProductCommandOutcomeRef(
                OnlyProductCommandOutcomeKind.QUALIFICATION_DECISION,
                decision.decision_fingerprint,
            ),
            completed_at,
        )
        self.receipts[admission.command_id.value] = receipt
        return receipt

    def records(self, strategy_fingerprint):  # type: ignore[no-untyped-def]
        return self.ledger.records(strategy_fingerprint)

    def append_promotion_with_receipt(self, record, command_id, command_fingerprint, qualification_authorization):  # type: ignore[no-untyped-def]
        del qualification_authorization
        existing = self.receipts.get(command_id.value)
        if existing is not None:
            return existing
        self.ledger.append(record)
        self.promotions[record.record_fingerprint] = record
        receipt = OnlyProductCommandReceipt(
            command_id,
            OnlyProductCommandKind.PROMOTE_STRATEGY,
            command_fingerprint,
            OnlyProductCommandOutcomeRef(
                OnlyProductCommandOutcomeKind.STRATEGY_PROMOTION,
                record.record_fingerprint,
            ),
            record.recorded_at,
        )
        self.receipts[command_id.value] = receipt
        return receipt

    def load_promotion(self, record_fingerprint):  # type: ignore[no-untyped-def]
        return self.promotions[record_fingerprint]


class _Evaluator:
    def __init__(self, decision: OnlyQualificationDecision, decisions: _OnlyQualificationDecisionPublisher) -> None:
        self.decision = decision
        self.decisions = decisions

    def evaluate(self, **kwargs):  # type: ignore[no-untyped-def]
        assert kwargs["subject_strategy_fingerprint"] == self.decision.subject_strategy_fingerprint
        assert kwargs["policy_id"] == self.decision.policy_id
        assert kwargs["policy_version"] == self.decision.policy_version
        assert kwargs["evidence"] == self.decision.evidence
        return self.decisions.publish_verified(_only_authorize_qualification_decision_publication(self.decision))


def _policy(gate: OnlyQualificationGate, version: str) -> OnlyQualificationPolicyRevision:
    kind = (
        OnlyQualificationEvidenceKind.RESEARCH_RESULT
        if gate is OnlyQualificationGate.RESEARCH_TO_BACKTEST
        else OnlyQualificationEvidenceKind.BACKTEST_EVIDENCE
    )
    metric = (
        "research.statistics_result_count"
        if kind is OnlyQualificationEvidenceKind.RESEARCH_RESULT
        else "backtest.artifact_count"
    )
    return OnlyQualificationPolicyRevision(
        "strategy-gate",
        version,
        gate,
        (OnlyQualificationCriterion("minimum", kind, metric, "GE", Decimal(1)),),
    )


def _decision(
    subject: str,
    policy: OnlyQualificationPolicyRevision,
    evidence: OnlyQualificationEvidenceReference,
    outcome: OnlyQualificationOutcome = OnlyQualificationOutcome.APPROVED,
) -> OnlyQualificationDecision:
    criterion = policy.criteria[0]
    return OnlyQualificationDecision(
        subject,
        policy.gate,
        policy.policy_id,
        policy.policy_version,
        policy.policy_fingerprint,
        (evidence,),
        (
            OnlyQualificationCriterionResult(
                criterion.criterion_id,
                evidence.evidence_fingerprint,
                criterion.metric,
                Decimal(1),
                criterion.comparison,
                criterion.threshold,
                (
                    OnlyQualificationCriterionOutcome.PASS
                    if outcome is OnlyQualificationOutcome.APPROVED
                    else OnlyQualificationCriterionOutcome.FAIL
                ),
            ),
        ),
        outcome,
    )


def _case(tmp_path):  # type: ignore[no-untyped-def]
    revision = p9_strategy_case(tmp_path / "case").revision
    semantic = tmp_path / "semantic"
    publish_frozen_strategy_for_execution_test(semantic, revision)
    strategies = OnlyFrozenStrategyRevisionStore(semantic)
    relation = strategies.freeze_relations(str(revision.strategy_fingerprint))[0]
    policies = OnlyQualificationPolicyStore(semantic)
    decisions, decision_publisher = _only_compose_qualification_decision_authority(semantic)
    store = _ProductStore()
    research_policy = policies.put(_policy(OnlyQualificationGate.RESEARCH_TO_BACKTEST, "1"))
    research_evidence = OnlyQualificationEvidenceReference(
        OnlyQualificationEvidenceKind.RESEARCH_RESULT,
        relation.research_result_fingerprint,
        "7" * 64,
        relation.relation_fingerprint,
    )
    research_decision = decision_publisher.publish_verified(
        _only_authorize_qualification_decision_publication(
            _decision(str(revision.strategy_fingerprint), research_policy, research_evidence)
        )
    )
    return revision, strategies, policies, decisions, decision_publisher, store, research_decision


def test_qualification_product_command_is_idempotent_and_conflict_safe(tmp_path) -> None:  # type: ignore[no-untyped-def]
    revision, _, _, decisions, decision_publisher, store, decision = _case(tmp_path)
    service = OnlyQualificationProductService(
        evaluator=_Evaluator(decision, decision_publisher),  # type: ignore[arg-type]
        decisions=decisions,
        store=store,  # type: ignore[arg-type]
        now_utc=lambda: NOW,
    )
    command_id = OnlyProductCommandId("00000000-0000-4000-8000-000000005000")
    request = {
        "command_id": command_id,
        "subject_strategy_fingerprint": str(revision.strategy_fingerprint),
        "policy_id": decision.policy_id,
        "policy_version": decision.policy_version,
        "evidence": decision.evidence,
    }
    first = service.evaluate(**request)
    second = service.evaluate(**request)
    assert first.decision == second.decision == decision
    assert not first.replayed and second.replayed
    with pytest.raises(OnlyQualificationError) as conflict:
        service.evaluate(**{**request, "policy_version": "2"})
    assert conflict.value.code == "PRODUCT_COMMAND_CONFLICT"


def test_approved_qualification_is_required_for_backtest_and_sim_promotion(tmp_path) -> None:  # type: ignore[no-untyped-def]
    revision, strategies, policies, decisions, decision_publisher, store, research_decision = _case(tmp_path)
    promotion = OnlyStrategyPromotionProductService(
        strategies=strategies,
        store=store,  # type: ignore[arg-type]
        qualification_decisions=decisions,
        qualification_policies=policies,
        audit_time=lambda: NOW,
    )
    subject = str(revision.strategy_fingerprint)
    with pytest.raises(OnlyStrategyPromotionError) as missing:
        promotion.promote_to_backtest(
            command_id=OnlyProductCommandId("00000000-0000-4000-8000-000000005001"),
            strategy_fingerprint=subject,
            qualification_decision_fingerprint="9" * 64,
            policy_fingerprint=research_decision.policy_fingerprint,
            reason="must fail",
            actor="operator",
        )
    assert missing.value.code == "QUALIFICATION_DECISION_CORRUPT"

    backtest_record, replayed = promotion.promote_to_backtest(
        command_id=OnlyProductCommandId("00000000-0000-4000-8000-000000005002"),
        strategy_fingerprint=subject,
        qualification_decision_fingerprint=research_decision.decision_fingerprint,
        policy_fingerprint=research_decision.policy_fingerprint,
        reason="qualified",
        actor="operator",
    )
    assert not replayed
    assert backtest_record.schema_version == 2
    assert backtest_record.qualification_decision_fingerprint == research_decision.decision_fingerprint
    assert backtest_record.to_stage is OnlyStrategyPromotionStage.BACKTEST

    backtest_policy = policies.put(_policy(OnlyQualificationGate.BACKTEST_TO_SIM, "2"))
    backtest_evidence = OnlyQualificationEvidenceReference(
        OnlyQualificationEvidenceKind.BACKTEST_EVIDENCE,
        "8" * 64,
    )
    backtest_decision = decision_publisher.publish_verified(
        _only_authorize_qualification_decision_publication(_decision(subject, backtest_policy, backtest_evidence))
    )
    sim_record, _ = promotion.promote_to_sim(
        command_id=OnlyProductCommandId("00000000-0000-4000-8000-000000005003"),
        strategy_fingerprint=subject,
        qualification_decision_fingerprint=backtest_decision.decision_fingerprint,
        policy_fingerprint=backtest_decision.policy_fingerprint,
        reason="eligible for SIM",
        actor="operator",
    )
    assert sim_record.to_stage is OnlyStrategyPromotionStage.SIM


def test_rejected_or_mismatched_qualification_cannot_promote(tmp_path) -> None:  # type: ignore[no-untyped-def]
    revision, strategies, policies, decisions, decision_publisher, store, approved = _case(tmp_path)
    rejected = decision_publisher.publish_verified(
        _only_authorize_qualification_decision_publication(
            _decision(
                str(revision.strategy_fingerprint),
                policies.load_exact(approved.policy_id, approved.policy_version),
                approved.evidence[0],
                OnlyQualificationOutcome.REJECTED,
            )
        )
    )
    promotion = OnlyStrategyPromotionProductService(
        strategies=strategies,
        store=store,  # type: ignore[arg-type]
        qualification_decisions=decisions,
        qualification_policies=policies,
        audit_time=lambda: NOW,
    )
    subject = str(revision.strategy_fingerprint)
    with pytest.raises(OnlyStrategyPromotionError) as blocked:
        promotion.promote_to_backtest(
            command_id=OnlyProductCommandId("00000000-0000-4000-8000-000000005004"),
            strategy_fingerprint=subject,
            qualification_decision_fingerprint=rejected.decision_fingerprint,
            policy_fingerprint=rejected.policy_fingerprint,
            reason="cannot override",
            actor="operator",
        )
    assert blocked.value.code == "QUALIFICATION_DECISION_NOT_APPROVED"
    with pytest.raises(OnlyStrategyPromotionError) as mismatch:
        promotion.promote_to_backtest(
            command_id=OnlyProductCommandId("00000000-0000-4000-8000-000000005005"),
            strategy_fingerprint=subject,
            qualification_decision_fingerprint=approved.decision_fingerprint,
            policy_fingerprint="f" * 64,
            reason="cannot substitute policy",
            actor="operator",
        )
    assert mismatch.value.code == "QUALIFICATION_DECISION_POLICY_MISMATCH"
