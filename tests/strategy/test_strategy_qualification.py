from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError, dataclass, replace
from decimal import Decimal
from types import SimpleNamespace

import pytest

from onlyalpha.backtest import OnlyBacktestEvidenceManifest, OnlyBacktestEvidenceStore
from onlyalpha.research import (
    OnlyResearchParameterNeighborhoodSummaryExecutor,
    OnlyResearchResultCandidatePlan,
    OnlyResearchStatisticsResultReference,
    OnlyResearchSummaryScalarStatus,
)
from onlyalpha.research.evaluation.errors import OnlyResearchStatisticsResultStoreError
from onlyalpha.research.evaluation.summary.result import OnlyResearchSummaryStatisticsResult
from onlyalpha.strategy import OnlyFrozenStrategyRevisionStore, OnlyQualificationError
from onlyalpha.strategy.freeze_relation import OnlyStrategyFreezeRelation
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
from tests.research.evaluation.support import coverage_case, factor_pair_effect_case, stability_case, summary_case
from tests.research.evaluation.test_parameter_neighborhood_summary import _effect_sources
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


@dataclass(slots=True)
class _RichStrategies:
    strategy_fingerprint: str
    relation: OnlyStrategyFreezeRelation

    def load_verified(self, fingerprint: str):  # type: ignore[no-untyped-def]
        if fingerprint != self.strategy_fingerprint:
            raise ValueError("STRATEGY_NOT_FOUND")
        return SimpleNamespace(strategy_fingerprint=fingerprint)

    def load_freeze_relation(self, fingerprint: str) -> OnlyStrategyFreezeRelation:
        if fingerprint != self.relation.relation_fingerprint:
            raise ValueError("FREEZE_RELATION_NOT_FOUND")
        return self.relation


@dataclass(slots=True)
class _RichStatistics:
    values: dict[str, object]
    failure: OnlyResearchStatisticsResultStoreError | None = None

    def load_verified(self, fingerprint: str) -> object:
        if self.failure is not None:
            raise self.failure
        if fingerprint not in self.values:
            raise OnlyResearchStatisticsResultStoreError("STATISTICS_RESULT_NOT_FOUND", fingerprint)
        return self.values[fingerprint]


@dataclass(slots=True)
class _RichResearchResults:
    locator: str
    manifest: object

    def load_verified(self, fingerprint: str):  # type: ignore[no-untyped-def]
        if fingerprint != self.locator:
            raise ValueError("RESEARCH_RESULT_NOT_FOUND")
        return SimpleNamespace(manifest=self.manifest)


def _candidate(candidate_fingerprint: str, statistics_fingerprints: tuple[str, ...]) -> OnlyResearchResultCandidatePlan:
    return OnlyResearchResultCandidatePlan(
        candidate_fingerprint,
        "factor",
        (),
        "a" * 64,
        "b" * 64,
        tuple(sorted(statistics_fingerprints)),
    )


def _rich_qualification_case(
    tmp_path,
    rich_results: tuple[object, ...],
    *,
    frozen_candidate_fingerprint: str,
    candidates: tuple[OnlyResearchResultCandidatePlan, ...] | None = None,
    reader: _RichStatistics | None = None,
    configure_reader: bool = True,
    result_schema_version: int = 2,
):  # type: ignore[no-untyped-def]
    strategy_fingerprint = "8" * 64
    result_fingerprint = "9" * 64
    locator = "7" * 64
    if candidates is None:
        candidates = (
            _candidate(
                frozen_candidate_fingerprint,
                tuple(item.manifest.statistics_fingerprint for item in rich_results),
            ),
        )
    references = tuple(
        sorted(
            OnlyResearchStatisticsResultReference(
                item.manifest.statistics_fingerprint,
                item.manifest.statistics_result_fingerprint,
            )
            for item in rich_results
        )
    )
    manifest = SimpleNamespace(
        schema_version=result_schema_version,
        plan=SimpleNamespace(candidates=candidates),
        research_result_fingerprint=result_fingerprint,
        dataset_snapshot_fingerprint=rich_results[0].manifest.dataset_snapshot_fingerprint,
        statistics_results=references,
        calculation_results=(),
    )
    relation = OnlyStrategyFreezeRelation(
        strategy_fingerprint,
        frozen_candidate_fingerprint,
        result_fingerprint,
        ("1" * 64,),
        "2" * 64,
        ("3" * 64,),
    )
    strategies = _RichStrategies(strategy_fingerprint, relation)
    policies = OnlyQualificationPolicyStore(tmp_path / "semantic")
    _, publisher = _only_compose_qualification_decision_authority(tmp_path / "semantic")
    evaluator = OnlyQualificationEvaluator(
        strategies=strategies,  # type: ignore[arg-type]
        policies=policies,
        research_results=_RichResearchResults(locator, manifest),  # type: ignore[arg-type]
        backtest_evidence=OnlyBacktestEvidenceStore(tmp_path),
        decisions=publisher,
        research_statistics=(
            reader or _RichStatistics({item.manifest.statistics_fingerprint: item for item in rich_results})
            if configure_reader
            else None
        ),
    )
    evidence = (
        OnlyQualificationEvidenceReference(
            OnlyQualificationEvidenceKind.RESEARCH_RESULT,
            result_fingerprint,
            locator,
            relation.relation_fingerprint,
        ),
    )
    return evaluator, policies, evidence, strategy_fingerprint


def _synthetic_summary_result(
    source: OnlyResearchSummaryStatisticsResult,
    statistics_fingerprint: str,
    statistics_result_fingerprint: str,
    *,
    plan: object | None = None,
    summary: object | None = None,
) -> OnlyResearchSummaryStatisticsResult:
    result = object.__new__(OnlyResearchSummaryStatisticsResult)
    object.__setattr__(
        result,
        "manifest",
        SimpleNamespace(
            statistics_fingerprint=statistics_fingerprint,
            statistics_result_fingerprint=statistics_result_fingerprint,
            dataset_snapshot_fingerprint=source.manifest.dataset_snapshot_fingerprint,
            plan=source.manifest.plan if plan is None else plan,
        ),
    )
    object.__setattr__(result, "summary", source.summary if summary is None else summary)
    return result


def _evaluate_rich(
    evaluator: OnlyQualificationEvaluator,
    policies: OnlyQualificationPolicyStore,
    evidence: tuple[OnlyQualificationEvidenceReference, ...],
    strategy_fingerprint: str,
    metric: str,
    threshold: Decimal,
    comparison: str = "EQ",
):  # type: ignore[no-untyped-def]
    policy = _policy(metric=metric, comparison=comparison, threshold=format(threshold, "f"))
    policies.put(policy)
    return evaluator.evaluate(
        subject_strategy_fingerprint=strategy_fingerprint,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        evidence=evidence,
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
    assert first.decision_fingerprint == "3fbc9df1f062f225ab3c63000f6551b8bfbcbd05abd350c4ce4b5741900242f2"
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


@pytest.mark.parametrize(
    ("case_factory", "metric", "field"),
    (
        (summary_case, "research.factor.ic.mean@1", "mean"),
        (coverage_case, "research.factor.ic.coverage.pair_count_total@1", "pair_count_total"),
        (stability_case, "research.factor.ic.stability.slice_count@1", "slice_count"),
    ),
)
def test_rich_candidate_summary_metrics_resolve_exact_registered_scalar(
    tmp_path, case_factory, metric: str, field: str
) -> None:  # type: ignore[no-untyped-def]
    case = case_factory(tmp_path)
    plan, store, executor = case[11], case[12], case[13]
    executor.execute(plan)
    rich = store.load_verified(plan.statistics_fingerprint)
    scalar = getattr(rich.summary, field)
    expected = Decimal(scalar.integer_value) if scalar.integer_value is not None else scalar.decimal_value
    assert expected is not None
    evaluator, policies, evidence, strategy = _rich_qualification_case(
        tmp_path,
        (rich,),
        frozen_candidate_fingerprint="c" * 64,
    )
    decision = _evaluate_rich(evaluator, policies, evidence, strategy, metric, expected)
    assert decision.outcome is OnlyQualificationOutcome.APPROVED
    assert decision.criterion_results[0].observed_value == expected


def test_effect_rich_metric_supports_approved_and_rejected_without_recomputation(tmp_path) -> None:  # type: ignore[no-untyped-def]
    case = summary_case(tmp_path)
    case[13].execute(case[11])
    rich = case[12].load_verified(case[11].statistics_fingerprint)
    value = rich.summary.mean.decimal_value
    assert value is not None
    evaluator, policies, evidence, strategy = _rich_qualification_case(
        tmp_path,
        (rich,),
        frozen_candidate_fingerprint="c" * 64,
    )
    approved = _evaluate_rich(
        evaluator,
        policies,
        evidence,
        strategy,
        "research.factor.ic.mean@1",
        value,
    )
    assert approved.outcome is OnlyQualificationOutcome.APPROVED

    other_root = tmp_path / "rejected"
    evaluator, policies, evidence, strategy = _rich_qualification_case(
        other_root,
        (rich,),
        frozen_candidate_fingerprint="c" * 64,
    )
    rejected = _evaluate_rich(
        evaluator,
        policies,
        evidence,
        strategy,
        "research.factor.ic.mean@1",
        value,
        "GT",
    )
    assert rejected.outcome is OnlyQualificationOutcome.REJECTED


def test_factor_pair_and_neighborhood_metrics_resolve_from_exact_candidate_membership(tmp_path) -> None:  # type: ignore[no-untyped-def]
    pair = factor_pair_effect_case(tmp_path / "pair")
    pair[15].execute(pair[13])
    pair_result = pair[14].load_verified(pair[13].statistics_fingerprint)
    pair_candidate = pair[13].first_operand.candidate_fingerprint
    pair_value = pair_result.summary.mean.decimal_value
    assert pair_value is not None
    evaluator, policies, evidence, strategy = _rich_qualification_case(
        tmp_path / "pair-qualification",
        (pair_result,),
        frozen_candidate_fingerprint=pair_candidate,
    )
    assert (
        _evaluate_rich(
            evaluator,
            policies,
            evidence,
            strategy,
            "research.factor_pair.correlation.mean@1",
            pair_value,
        ).outcome
        is OnlyQualificationOutcome.APPROVED
    )

    effect_case, _, bindings, neighborhood_plan = _effect_sources(tmp_path / "neighborhood", 3)
    OnlyResearchParameterNeighborhoodSummaryExecutor(effect_case[12]).execute(neighborhood_plan)
    neighborhood = effect_case[12].load_verified(neighborhood_plan.statistics_fingerprint)
    neighbor_count = neighborhood.summary.neighbor_count.integer_value
    assert neighbor_count is not None
    evaluator, policies, evidence, strategy = _rich_qualification_case(
        tmp_path / "neighborhood-qualification",
        (neighborhood,),
        frozen_candidate_fingerprint=bindings[0].candidate_fingerprint,
    )
    decision = _evaluate_rich(
        evaluator,
        policies,
        evidence,
        strategy,
        "research.factor.neighborhood.ic.neighbor_count@1",
        Decimal(neighbor_count),
    )
    assert decision.criterion_results[0].observed_value == Decimal(neighbor_count)


def test_integer_conversion_is_exact_beyond_binary_float_range(tmp_path) -> None:  # type: ignore[no-untyped-def]
    case = coverage_case(tmp_path)
    case[13].execute(case[11])
    rich = case[12].load_verified(case[11].statistics_fingerprint)
    large = 9007199254740993
    summary = replace(
        rich.summary,
        pair_count_total=replace(rich.summary.pair_count_total, integer_value=large),
    )
    rich = replace(rich, summary=summary)
    evaluator, policies, evidence, strategy = _rich_qualification_case(
        tmp_path / "qualification",
        (rich,),
        frozen_candidate_fingerprint="c" * 64,
    )
    decision = _evaluate_rich(
        evaluator,
        policies,
        evidence,
        strategy,
        "research.factor.ic.coverage.pair_count_total@1",
        Decimal(large),
    )
    assert decision.criterion_results[0].observed_value == Decimal("9007199254740993")


def test_global_only_summary_and_missing_rich_reader_fail_closed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    case = summary_case(tmp_path)
    case[13].execute(case[11])
    rich = case[12].load_verified(case[11].statistics_fingerprint)
    empty_candidate = _candidate("c" * 64, ())
    evaluator, policies, evidence, strategy = _rich_qualification_case(
        tmp_path / "global-only",
        (rich,),
        frozen_candidate_fingerprint="c" * 64,
        candidates=(empty_candidate,),
    )
    policies.put(_policy(metric="research.factor.ic.mean@1"))
    with pytest.raises(OnlyQualificationError) as missing:
        evaluator.evaluate(
            subject_strategy_fingerprint=strategy,
            policy_id="strategy-gate",
            policy_version="1",
            evidence=evidence,
        )
    assert missing.value.code == "QUALIFICATION_REQUIRED_EVIDENCE_MISSING"

    evaluator, policies, evidence, strategy = _rich_qualification_case(
        tmp_path / "no-reader",
        (rich,),
        frozen_candidate_fingerprint="c" * 64,
        configure_reader=False,
    )
    policies.put(_policy(metric="research.factor.ic.mean@1"))
    with pytest.raises(OnlyQualificationError) as no_reader:
        evaluator.evaluate(
            subject_strategy_fingerprint=strategy,
            policy_id="strategy-gate",
            policy_version="1",
            evidence=evidence,
        )
    assert no_reader.value.code == "QUALIFICATION_REQUIRED_EVIDENCE_MISSING"


def test_non_valid_scalar_and_missing_or_corrupt_statistics_fail_closed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    pair = factor_pair_effect_case(tmp_path / "pair")
    pair[15].execute(pair[13])
    rich = pair[14].load_verified(pair[13].statistics_fingerprint)
    invalid = replace(
        rich,
        summary=replace(
            rich.summary,
            stddev_sample=replace(
                rich.summary.stddev_sample,
                status=OnlyResearchSummaryScalarStatus.INSUFFICIENT_OBSERVATIONS,
                decimal_value=None,
            ),
        ),
    )
    metric = "research.factor_pair.correlation.stddev_sample@1"
    candidate = pair[13].first_operand.candidate_fingerprint
    evaluator, policies, evidence, strategy = _rich_qualification_case(
        tmp_path / "invalid",
        (invalid,),
        frozen_candidate_fingerprint=candidate,
    )
    policies.put(_policy(metric=metric))
    with pytest.raises(OnlyQualificationError) as unavailable:
        evaluator.evaluate(
            subject_strategy_fingerprint=strategy,
            policy_id="strategy-gate",
            policy_version="1",
            evidence=evidence,
        )
    assert unavailable.value.code == "QUALIFICATION_REQUIRED_EVIDENCE_INVALID"

    for code, expected in (
        ("STATISTICS_RESULT_NOT_FOUND", "QUALIFICATION_EVIDENCE_NOT_FOUND"),
        ("STATISTICS_RESULT_CORRUPT", "QUALIFICATION_EVIDENCE_CORRUPT"),
    ):
        root = tmp_path / code.lower()
        reader = _RichStatistics({}, OnlyResearchStatisticsResultStoreError(code, "failure"))
        evaluator, policies, evidence, strategy = _rich_qualification_case(
            root,
            (rich,),
            frozen_candidate_fingerprint=candidate,
            reader=reader,
        )
        policies.put(_policy(metric="research.factor_pair.correlation.mean@1"))
        with pytest.raises(OnlyQualificationError) as failure:
            evaluator.evaluate(
                subject_strategy_fingerprint=strategy,
                policy_id="strategy-gate",
                policy_version="1",
                evidence=evidence,
            )
        assert failure.value.code == expected


def test_frozen_candidate_isolation_excludes_other_candidate_and_global_summary(tmp_path) -> None:  # type: ignore[no-untyped-def]
    case = summary_case(tmp_path)
    case[13].execute(case[11])
    frozen = case[12].load_verified(case[11].statistics_fingerprint)
    frozen_value = frozen.summary.mean.decimal_value
    assert frozen_value is not None
    other_candidate = "d" * 64
    other_plan = replace(frozen.manifest.plan, subject_candidate_fingerprint=other_candidate)
    other_summary = replace(
        frozen.summary,
        mean=replace(frozen.summary.mean, decimal_value=frozen_value + Decimal("1.000000000000")),
    )
    other = _synthetic_summary_result(
        frozen,
        "e" * 64,
        "f" * 64,
        plan=other_plan,
        summary=other_summary,
    )
    candidates = (
        _candidate("c" * 64, (frozen.manifest.statistics_fingerprint,)),
        _candidate(other_candidate, (other.manifest.statistics_fingerprint,)),
    )
    evaluator, policies, evidence, strategy = _rich_qualification_case(
        tmp_path / "qualification",
        (frozen, other),
        frozen_candidate_fingerprint="c" * 64,
        candidates=tuple(sorted(candidates)),
    )
    decision = _evaluate_rich(
        evaluator,
        policies,
        evidence,
        strategy,
        "research.factor.ic.mean@1",
        frozen_value,
    )
    assert decision.outcome is OnlyQualificationOutcome.APPROVED


def test_exactly_one_scalar_rule_rejects_factor_pair_ambiguity(tmp_path) -> None:  # type: ignore[no-untyped-def]
    case = factor_pair_effect_case(tmp_path)
    case[15].execute(case[13])
    first = case[14].load_verified(case[13].statistics_fingerprint)
    second_plan = replace(
        first.manifest.plan,
        second_operand=replace(first.manifest.plan.second_operand, candidate_fingerprint="d" * 64),
    )
    second = _synthetic_summary_result(first, "e" * 64, "f" * 64, plan=second_plan)
    candidate = case[13].first_operand.candidate_fingerprint
    evaluator, policies, evidence, strategy = _rich_qualification_case(
        tmp_path / "qualification",
        (first, second),
        frozen_candidate_fingerprint=candidate,
    )
    policies.put(_policy(metric="research.factor_pair.correlation.mean@1"))
    with pytest.raises(OnlyQualificationError) as ambiguous:
        evaluator.evaluate(
            subject_strategy_fingerprint=strategy,
            policy_id="strategy-gate",
            policy_version="1",
            evidence=evidence,
        )
    assert ambiguous.value.code == "QUALIFICATION_EVIDENCE_AMBIGUOUS"


def test_result_v1_and_legacy_only_v2_cannot_rich_qualify(tmp_path) -> None:  # type: ignore[no-untyped-def]
    case = summary_case(tmp_path)
    legacy = case[8].load_verified(case[6].statistics_fingerprint)
    for schema_version in (1, 2):
        root = tmp_path / f"v{schema_version}"
        evaluator, policies, evidence, strategy = _rich_qualification_case(
            root,
            (legacy,),
            frozen_candidate_fingerprint="c" * 64,
            result_schema_version=schema_version,
        )
        policies.put(_policy(metric="research.factor.ic.mean@1"))
        with pytest.raises(OnlyQualificationError) as missing:
            evaluator.evaluate(
                subject_strategy_fingerprint=strategy,
                policy_id="strategy-gate",
                policy_version="1",
                evidence=evidence,
            )
        assert missing.value.code == "QUALIFICATION_REQUIRED_EVIDENCE_MISSING"


def test_missing_or_mismatched_frozen_candidate_fails_closed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    case = summary_case(tmp_path)
    case[13].execute(case[11])
    rich = case[12].load_verified(case[11].statistics_fingerprint)
    evaluator, policies, evidence, strategy = _rich_qualification_case(
        tmp_path / "missing",
        (rich,),
        frozen_candidate_fingerprint="c" * 64,
        candidates=(_candidate("d" * 64, (rich.manifest.statistics_fingerprint,)),),
    )
    policies.put(_policy(metric="research.factor.ic.mean@1"))
    with pytest.raises(OnlyQualificationError) as missing:
        evaluator.evaluate(
            subject_strategy_fingerprint=strategy,
            policy_id="strategy-gate",
            policy_version="1",
            evidence=evidence,
        )
    assert missing.value.code == "QUALIFICATION_EVIDENCE_SUBJECT_MISMATCH"

    wrong_plan = replace(rich.manifest.plan, subject_candidate_fingerprint="d" * 64)
    mismatched = _synthetic_summary_result(rich, "e" * 64, "f" * 64, plan=wrong_plan)
    evaluator, policies, evidence, strategy = _rich_qualification_case(
        tmp_path / "mismatch",
        (mismatched,),
        frozen_candidate_fingerprint="c" * 64,
    )
    policies.put(_policy(metric="research.factor.ic.mean@1"))
    with pytest.raises(OnlyQualificationError) as mismatch:
        evaluator.evaluate(
            subject_strategy_fingerprint=strategy,
            policy_id="strategy-gate",
            policy_version="1",
            evidence=evidence,
        )
    assert mismatch.value.code == "QUALIFICATION_EVIDENCE_SUBJECT_MISMATCH"


def test_zero_variance_and_no_valid_observations_are_not_numeric_evidence(tmp_path) -> None:  # type: ignore[no-untyped-def]
    effect_case = summary_case(tmp_path)
    effect_case[13].execute(effect_case[11])
    effect = effect_case[12].load_verified(effect_case[11].statistics_fingerprint)
    zero_variance = _synthetic_summary_result(
        effect,
        effect.manifest.statistics_fingerprint,
        effect.manifest.statistics_result_fingerprint,
        summary=SimpleNamespace(
            summary_kind=effect.summary.summary_kind,
            information_ratio=replace(
                effect.summary.information_ratio,
                status=OnlyResearchSummaryScalarStatus.ZERO_VARIANCE,
                decimal_value=None,
            ),
        ),
    )
    evaluator, policies, evidence, strategy = _rich_qualification_case(
        tmp_path / "zero-variance",
        (zero_variance,),
        frozen_candidate_fingerprint="c" * 64,
    )
    policies.put(_policy(metric="research.factor.ic.ir@1"))
    with pytest.raises(OnlyQualificationError) as zero:
        evaluator.evaluate(
            subject_strategy_fingerprint=strategy,
            policy_id="strategy-gate",
            policy_version="1",
            evidence=evidence,
        )
    assert zero.value.code == "QUALIFICATION_REQUIRED_EVIDENCE_INVALID"

    pair_case = factor_pair_effect_case(tmp_path / "pair")
    pair_case[15].execute(pair_case[13])
    pair = pair_case[14].load_verified(pair_case[13].statistics_fingerprint)
    no_valid = _synthetic_summary_result(
        pair,
        pair.manifest.statistics_fingerprint,
        pair.manifest.statistics_result_fingerprint,
        summary=SimpleNamespace(
            summary_kind=pair.summary.summary_kind,
            mean=replace(
                pair.summary.mean,
                status=OnlyResearchSummaryScalarStatus.NO_VALID_OBSERVATIONS,
                decimal_value=None,
            ),
        ),
    )
    evaluator, policies, evidence, strategy = _rich_qualification_case(
        tmp_path / "no-valid",
        (no_valid,),
        frozen_candidate_fingerprint=pair_case[13].first_operand.candidate_fingerprint,
    )
    policies.put(_policy(metric="research.factor_pair.correlation.mean@1"))
    with pytest.raises(OnlyQualificationError) as absent:
        evaluator.evaluate(
            subject_strategy_fingerprint=strategy,
            policy_id="strategy-gate",
            policy_version="1",
            evidence=evidence,
        )
    assert absent.value.code == "QUALIFICATION_REQUIRED_EVIDENCE_INVALID"


def test_rich_decision_fingerprint_is_identical_in_a_fresh_process(tmp_path) -> None:  # type: ignore[no-untyped-def]
    research_root = tmp_path / "research"
    qualification_root = tmp_path / "qualification"
    case = summary_case(research_root)
    case[13].execute(case[11])
    rich = case[12].load_verified(case[11].statistics_fingerprint)
    value = rich.summary.mean.decimal_value
    assert value is not None
    evaluator, policies, evidence, strategy = _rich_qualification_case(
        qualification_root,
        (rich,),
        frozen_candidate_fingerprint="c" * 64,
    )
    expected = _evaluate_rich(
        evaluator,
        policies,
        evidence,
        strategy,
        "research.factor.ic.mean@1",
        value,
    ).decision_fingerprint
    script = r"""
import sys
from decimal import Decimal
from pathlib import Path
from tests.research.evaluation.support import summary_case
from tests.strategy.test_strategy_qualification import _evaluate_rich, _rich_qualification_case
research_root, qualification_root = map(Path, sys.argv[1:])
case = summary_case(research_root)
case[13].execute(case[11])
rich = case[12].load_verified(case[11].statistics_fingerprint)
value = rich.summary.mean.decimal_value
evaluator, policies, evidence, strategy = _rich_qualification_case(
    qualification_root, (rich,), frozen_candidate_fingerprint="c" * 64
)
decision = _evaluate_rich(
    evaluator, policies, evidence, strategy, "research.factor.ic.mean@1", Decimal(value)
)
print(decision.decision_fingerprint)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(research_root), str(qualification_root)],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONHASHSEED": "947"},
    )
    assert completed.stdout.strip() == expected
