from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError, dataclass
from decimal import Decimal
from types import SimpleNamespace

import pytest

from onlyalpha.backtest import OnlyBacktestEvidenceManifest, OnlyBacktestEvidenceStore
from onlyalpha.strategy import OnlyFrozenStrategyRevisionStore, OnlyQualificationError
from onlyalpha.strategy.qualification import (
    OnlyQualificationCriterion,
    OnlyQualificationEvaluator,
    OnlyQualificationEvidenceKind,
    OnlyQualificationEvidenceReference,
    OnlyQualificationGate,
    OnlyQualificationOutcome,
    OnlyQualificationPolicyRevision,
)
from onlyalpha.strategy.qualification_store import (
    OnlyQualificationPolicyStore,
    _only_compose_qualification_decision_authority,
)
from tests.strategy.p9_support import p9_strategy_case, publish_frozen_strategy_for_execution_test


@dataclass(slots=True)
class _ResearchResults:
    plan_fingerprint: str
    result_fingerprint: str
    statistics_count: int = 1
    calculation_count: int = 2

    def load_verified(self, plan_fingerprint: str):  # type: ignore[no-untyped-def]
        if plan_fingerprint != self.plan_fingerprint:
            raise ValueError("RESEARCH_RESULT_NOT_FOUND")
        return SimpleNamespace(
            manifest=SimpleNamespace(
                research_result_fingerprint=self.result_fingerprint,
                statistics_results=(object(),) * self.statistics_count,
                calculation_results=(object(),) * self.calculation_count,
            )
        )


def _policy(
    gate: OnlyQualificationGate = OnlyQualificationGate.RESEARCH_TO_BACKTEST,
    *,
    version: str = "1",
    metric: str = "research.statistics_result_count",
    comparison: str = "GE",
    threshold: str = "1",
) -> OnlyQualificationPolicyRevision:
    kind = (
        OnlyQualificationEvidenceKind.RESEARCH_RESULT
        if gate is OnlyQualificationGate.RESEARCH_TO_BACKTEST
        else OnlyQualificationEvidenceKind.BACKTEST_EVIDENCE
    )
    return OnlyQualificationPolicyRevision(
        "strategy-gate",
        version,
        gate,
        (OnlyQualificationCriterion("minimum-evidence", kind, metric, comparison, Decimal(threshold)),),
    )


def _backtest_manifest(strategy_fingerprint: str) -> tuple[OnlyBacktestEvidenceManifest, bytes]:
    payload = b'{"result":"immutable"}'
    return (
        OnlyBacktestEvidenceManifest(
            backtest_run_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            specification_fingerprint="a" * 64,
            admission_resolution_fingerprint="b" * 64,
            strategy_fingerprint=strategy_fingerprint,
            dataset_binding_fingerprint="d" * 64,
            base_dataset_snapshot_fingerprint="2" * 64,
            market_product_composition_fingerprint="e" * 64,
            portfolio_profile_fingerprint="3" * 64,
            risk_profile_fingerprint="4" * 64,
            execution_profile_fingerprint="5" * 64,
            kernel_semantics_version="kernel-v1",
            implementation_fingerprints=("6" * 64,),
            result_fingerprint="f" * 64,
            determinism_fingerprint="1" * 64,
            artifacts=(("result.json", hashlib.sha256(payload).hexdigest(), len(payload), "application/json"),),
        ),
        payload,
    )


def _research_case(tmp_path):  # type: ignore[no-untyped-def]
    revision = p9_strategy_case(tmp_path / "case").revision
    semantic = tmp_path / "semantic"
    publish_frozen_strategy_for_execution_test(semantic, revision)
    strategies = OnlyFrozenStrategyRevisionStore(semantic)
    relation = strategies.freeze_relations(str(revision.strategy_fingerprint))[0]
    policies = OnlyQualificationPolicyStore(semantic)
    decisions, decision_publisher = _only_compose_qualification_decision_authority(semantic)
    result_plan = "7" * 64
    results = _ResearchResults(result_plan, relation.research_result_fingerprint)
    backtests = OnlyBacktestEvidenceStore(tmp_path)
    evaluator = OnlyQualificationEvaluator(
        strategies=strategies,
        policies=policies,
        research_results=results,  # type: ignore[arg-type]
        backtest_evidence=backtests,
        decisions=decision_publisher,
    )
    evidence = (
        OnlyQualificationEvidenceReference(
            OnlyQualificationEvidenceKind.RESEARCH_RESULT,
            relation.research_result_fingerprint,
            result_plan,
            relation.relation_fingerprint,
        ),
    )
    return revision, relation, policies, decisions, evaluator, evidence, backtests


def test_policy_identity_is_canonical_put_once_and_exact_only(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = OnlyQualificationPolicyStore(tmp_path)
    first = _policy()
    assert first.policy_fingerprint == _policy().policy_fingerprint
    assert store.put(first) == first
    assert store.load_exact("strategy-gate", "1") == first
    assert store.policies() == (first,)
    with pytest.raises(OnlyQualificationError) as missing:
        store.load_exact("strategy-gate", "2")
    assert missing.value.code == "QUALIFICATION_POLICY_NOT_FOUND"
    with pytest.raises(OnlyQualificationError) as conflict:
        store.put(_policy(threshold="2"))
    assert conflict.value.code == "QUALIFICATION_POLICY_IDENTITY_CONFLICT"
    with pytest.raises(FrozenInstanceError):
        first.policy_version = "2"  # type: ignore[misc]


def test_policy_and_decision_authority_symlink_roots_fail_closed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    external = tmp_path / "external"
    external.mkdir()
    policy_root = tmp_path / "policy-semantic" / "strategy"
    policy_root.mkdir(parents=True)
    (policy_root / "qualification-policies").symlink_to(external, target_is_directory=True)
    with pytest.raises(OnlyQualificationError, match="QUALIFICATION_POLICY_IDENTITY_CONFLICT"):
        OnlyQualificationPolicyStore(tmp_path / "policy-semantic").put(_policy())

    decision_root = tmp_path / "decision-semantic" / "strategy" / "qualification-decisions"
    decision_root.mkdir(parents=True)
    (decision_root / "sha256").symlink_to(external, target_is_directory=True)
    decisions, _ = _only_compose_qualification_decision_authority(tmp_path / "decision-semantic")
    with pytest.raises(OnlyQualificationError, match="QUALIFICATION_DECISION_CORRUPT"):
        decisions.load_verified("a" * 64)


def test_same_subject_policy_and_research_evidence_is_deterministic_and_replayable(tmp_path) -> None:  # type: ignore[no-untyped-def]
    revision, _, policies, decisions, evaluator, evidence, _ = _research_case(tmp_path)
    policies.put(_policy())
    subject = str(revision.strategy_fingerprint)

    first = evaluator.evaluate(
        subject_strategy_fingerprint=subject,
        policy_id="strategy-gate",
        policy_version="1",
        evidence=evidence,
    )
    second = evaluator.evaluate(
        subject_strategy_fingerprint=subject,
        policy_id="strategy-gate",
        policy_version="1",
        evidence=evidence,
    )

    assert first == second == decisions.load_verified(first.decision_fingerprint)
    assert first.outcome is OnlyQualificationOutcome.APPROVED
    assert evaluator.replay(first.decision_fingerprint) == first


def test_new_policy_and_new_evidence_produce_new_immutable_decisions(tmp_path) -> None:  # type: ignore[no-untyped-def]
    revision, relation, policies, decisions, evaluator, evidence, _ = _research_case(tmp_path)
    policies.put(_policy(threshold="2"))
    rejected = evaluator.evaluate(
        subject_strategy_fingerprint=str(revision.strategy_fingerprint),
        policy_id="strategy-gate",
        policy_version="1",
        evidence=evidence,
    )
    policies.put(_policy(version="2", threshold="1"))
    approved = evaluator.evaluate(
        subject_strategy_fingerprint=str(revision.strategy_fingerprint),
        policy_id="strategy-gate",
        policy_version="2",
        evidence=evidence,
    )
    changed_evidence = (
        OnlyQualificationEvidenceReference(
            OnlyQualificationEvidenceKind.RESEARCH_RESULT,
            relation.research_result_fingerprint,
            "8" * 64,
            relation.relation_fingerprint,
        ),
    )

    assert rejected.outcome is OnlyQualificationOutcome.REJECTED
    assert approved.outcome is OnlyQualificationOutcome.APPROVED
    assert rejected.decision_fingerprint != approved.decision_fingerprint
    assert decisions.load_verified(rejected.decision_fingerprint) == rejected
    with pytest.raises(OnlyQualificationError) as missing:
        evaluator.evaluate(
            subject_strategy_fingerprint=str(revision.strategy_fingerprint),
            policy_id="strategy-gate",
            policy_version="2",
            evidence=changed_evidence,
        )
    assert missing.value.code == "QUALIFICATION_EVIDENCE_NOT_FOUND"


@pytest.mark.parametrize(
    ("policy", "expected"),
    (
        (_policy(metric="research.unknown"), "QUALIFICATION_POLICY_UNSUPPORTED"),
        (_policy(comparison="APPROX"), "QUALIFICATION_POLICY_UNSUPPORTED"),
    ),
)
def test_unsupported_policy_semantics_fail_closed(tmp_path, policy, expected) -> None:  # type: ignore[no-untyped-def]
    revision, _, policies, _, evaluator, evidence, _ = _research_case(tmp_path)
    policies.put(policy)
    with pytest.raises(OnlyQualificationError) as error:
        evaluator.evaluate(
            subject_strategy_fingerprint=str(revision.strategy_fingerprint),
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            evidence=evidence,
        )
    assert error.value.code == expected


def test_research_evidence_from_another_subject_fails_closed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    revision, _, policies, _, evaluator, evidence, _ = _research_case(tmp_path)
    other_case = p9_strategy_case(tmp_path / "other")
    other = next(
        item
        for item in other_case.revision_variants
        if str(item.strategy_fingerprint) != str(revision.strategy_fingerprint)
    )
    publish_frozen_strategy_for_execution_test(tmp_path / "semantic", other)
    policies.put(_policy())
    with pytest.raises(OnlyQualificationError) as error:
        evaluator.evaluate(
            subject_strategy_fingerprint=str(other.strategy_fingerprint),
            policy_id="strategy-gate",
            policy_version="1",
            evidence=evidence,
        )
    assert error.value.code == "QUALIFICATION_EVIDENCE_SUBJECT_MISMATCH"
    assert str(revision.strategy_fingerprint) != str(other.strategy_fingerprint)


def test_backtest_evidence_is_exact_typed_and_bound_to_subject(tmp_path) -> None:  # type: ignore[no-untyped-def]
    revision, _, policies, _, evaluator, _, backtests = _research_case(tmp_path)
    manifest, payload = _backtest_manifest(str(revision.strategy_fingerprint))
    backtests.publish(manifest, {"result.json": payload})
    policy = _policy(
        OnlyQualificationGate.BACKTEST_TO_SIM,
        metric="backtest.artifact_count",
    )
    policies.put(policy)
    decision = evaluator.evaluate(
        subject_strategy_fingerprint=str(revision.strategy_fingerprint),
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        evidence=(
            OnlyQualificationEvidenceReference(
                OnlyQualificationEvidenceKind.BACKTEST_EVIDENCE,
                manifest.evidence_fingerprint,
            ),
        ),
    )
    assert decision.gate is OnlyQualificationGate.BACKTEST_TO_SIM
    assert decision.outcome is OnlyQualificationOutcome.APPROVED


def test_missing_or_wrong_gate_evidence_fails_closed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    revision, _, policies, _, evaluator, _, _ = _research_case(tmp_path)
    policy = _policy(OnlyQualificationGate.BACKTEST_TO_SIM, metric="backtest.artifact_count")
    policies.put(policy)
    with pytest.raises(OnlyQualificationError) as missing:
        evaluator.evaluate(
            subject_strategy_fingerprint=str(revision.strategy_fingerprint),
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            evidence=(
                OnlyQualificationEvidenceReference(
                    OnlyQualificationEvidenceKind.BACKTEST_EVIDENCE,
                    "9" * 64,
                ),
            ),
        )
    assert missing.value.code == "QUALIFICATION_EVIDENCE_NOT_FOUND"
