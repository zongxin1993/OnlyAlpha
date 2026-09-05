from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from onlyalpha_http_server.strategy.routes import create_strategy_router

from onlyalpha.strategy.promotion import (
    OnlyStrategyPromotionDecision,
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
)


def _policy() -> OnlyQualificationPolicyRevision:
    return OnlyQualificationPolicyRevision(
        "research-gate",
        "1",
        OnlyQualificationGate.RESEARCH_TO_BACKTEST,
        (
            OnlyQualificationCriterion(
                "has-statistics",
                OnlyQualificationEvidenceKind.RESEARCH_RESULT,
                "research.statistics_result_count",
                "GE",
                Decimal(1),
            ),
        ),
    )


def _decision(policy: OnlyQualificationPolicyRevision) -> OnlyQualificationDecision:
    evidence = OnlyQualificationEvidenceReference(
        OnlyQualificationEvidenceKind.RESEARCH_RESULT,
        "b" * 64,
        "c" * 64,
        "d" * 64,
    )
    return OnlyQualificationDecision(
        "a" * 64,
        policy.gate,
        policy.policy_id,
        policy.policy_version,
        policy.policy_fingerprint,
        (evidence,),
        (
            OnlyQualificationCriterionResult(
                "has-statistics",
                evidence.evidence_fingerprint,
                "research.statistics_result_count",
                Decimal(1),
                "GE",
                Decimal(1),
                OnlyQualificationCriterionOutcome.PASS,
            ),
        ),
        OnlyQualificationOutcome.APPROVED,
    )


def test_qualification_command_query_and_promotion_http_contract() -> None:
    policy = _policy()
    decision = _decision(policy)
    promotion = OnlyStrategyPromotionRecord(
        "a" * 64,
        OnlyStrategyPromotionStage.RESEARCH,
        OnlyStrategyPromotionStage.BACKTEST,
        tuple(sorted(("d" * 64, decision.decision_fingerprint))),
        OnlyStrategyPromotionDecision.APPROVED,
        "qualified",
        "operator",
        datetime(2026, 9, 5, tzinfo=UTC),
        qualification_decision_fingerprint=decision.decision_fingerprint,
        schema_version=2,
    )

    class _Qualification:
        def evaluate(self, **kwargs):  # type: ignore[no-untyped-def]
            assert kwargs["policy_id"] == policy.policy_id
            assert kwargs["evidence"] == decision.evidence
            return SimpleNamespace(decision=decision, replayed=False)

    class _QualificationQuery:
        def policies(self):  # type: ignore[no-untyped-def]
            return (policy,)

        def policy(self, policy_id, policy_version):  # type: ignore[no-untyped-def]
            assert (policy_id, policy_version) == (policy.policy_id, policy.policy_version)
            return policy

        def decision(self, fingerprint):  # type: ignore[no-untyped-def]
            assert fingerprint == decision.decision_fingerprint
            return decision

        def decisions_for_subject(self, subject):  # type: ignore[no-untyped-def]
            assert subject == decision.subject_strategy_fingerprint
            return (decision,)

    class _Promotion:
        def promote_to_backtest(self, **kwargs):  # type: ignore[no-untyped-def]
            assert kwargs["qualification_decision_fingerprint"] == decision.decision_fingerprint
            return promotion, False

        def promote_to_sim(self, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError(kwargs)

    app = FastAPI()
    app.include_router(
        create_strategy_router(
            SimpleNamespace(),  # type: ignore[arg-type]
            _Promotion(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            _Qualification(),  # type: ignore[arg-type]
            _QualificationQuery(),  # type: ignore[arg-type]
        )
    )
    client = TestClient(app)
    headers = {"Idempotency-Key": "00000000-0000-4000-8000-000000006000"}
    body = {
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
        "evidence": [item.to_dict() for item in decision.evidence],
    }
    response = client.post("/api/v2/strategies/" + "a" * 64 + "/qualifications", headers=headers, json=body)
    assert response.status_code == 202, response.json()
    assert response.json()["decision"]["decision_fingerprint"] == decision.decision_fingerprint
    assert (
        client.get("/api/v2/qualification-policies").json()["policies"][0]["policy_fingerprint"]
        == policy.policy_fingerprint
    )

    promotion_response = client.post(
        "/api/v2/strategies/" + "a" * 64 + "/qualification-promotions",
        headers={"Idempotency-Key": "00000000-0000-4000-8000-000000006001"},
        json={
            "to_stage": "BACKTEST",
            "qualification_decision_fingerprint": decision.decision_fingerprint,
            "policy_fingerprint": policy.policy_fingerprint,
            "reason": "qualified",
            "actor": "operator",
        },
    )
    assert promotion_response.status_code == 202
    assert promotion_response.json()["to_stage"] == "BACKTEST"


def test_legacy_freeze_only_promotion_is_fail_closed() -> None:
    app = FastAPI()
    app.include_router(
        create_strategy_router(
            SimpleNamespace(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
        )
    )
    with pytest.raises(RuntimeError, match="QUALIFICATION_DECISION_NOT_APPROVED"):
        TestClient(app).post(
            "/api/v2/strategies/" + "a" * 64 + "/promotions",
            headers={"Idempotency-Key": "00000000-0000-4000-8000-000000006002"},
            json={"freeze_relation_fingerprint": "b" * 64, "reason": "legacy", "actor": "operator"},
        )
