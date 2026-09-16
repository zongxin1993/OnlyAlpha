from __future__ import annotations

import inspect
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from threading import Barrier

import pytest

from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.evaluation import OnlyExactEvaluationIntentSubjectV1
from onlyalpha.research.memory.projector import (
    OnlyExperimentMemoryProjectionV1,
    OnlyMemoryProjectionRecordV1,
    OnlyMemorySourceRefV1,
)
from onlyalpha.research.memory.query import (
    OnlyExactFailureEvidenceSelectorV1,
    OnlyMemoryHistoricalProofStatus,
    OnlyMemoryHistoricalProofV1,
    OnlyResearchRunTerminalOwnerV1,
    OnlySearchFailureOwnerV1,
)
from onlyalpha.research.memory.source_manifest import MANDATORY_FAMILIES
from onlyalpha.research.novelty import (
    OnlyHistoricalProofUnavailableError,
    OnlyNoveltyDecisionAuthority,
    OnlyNoveltyDecisionBundleV2,
    OnlyNoveltyDecisionConflictError,
    OnlyNoveltyDecisionCorruptError,
    OnlyNoveltyDecisionError,
    OnlyNoveltyDecisionNotFoundError,
    OnlyNoveltyDecisionReason,
    OnlyNoveltyDecisionRequestV1,
    OnlyNoveltyDecisionRequestV2,
    OnlyNoveltyDecisionSchemaUnsupportedError,
    OnlyNoveltyPolicyCondition,
    OnlyNoveltyPolicyOutcome,
    OnlyNoveltyPolicyStore,
    OnlyNoveltyQualificationBindingV1,
    OnlyNoveltyWitnessCorruptError,
    OnlyNoveltyWitnessSchemaUnsupportedError,
    only_verify_historical_novelty_decision,
)
from onlyalpha.research.source_cut import OnlySourceClosedCutV1
from onlyalpha.strategy.freeze_relation import OnlyStrategyFreezeRelation
from onlyalpha.strategy.qualification import (
    OnlyQualificationCriterionOutcome,
    OnlyQualificationCriterionResult,
    OnlyQualificationDecision,
    OnlyQualificationEvidenceKind,
    OnlyQualificationEvidenceReference,
    OnlyQualificationGate,
    OnlyQualificationOutcome,
)
from tests.research.evaluation.test_subject import _resolve, _scientific
from tests.research.memory.test_query import (
    CANDIDATE,
    DATASET,
    FAILED_RUN_ID,
    PLAN,
    RESULT,
    _intent_subject,
    _projection,
    _semantic_query,
    _store,
)
from tests.research.novelty.test_policy import policy

COMMAND = OnlyProductCommandId("00000000-0000-4000-8000-000000000010")


def _request(projection: OnlyExperimentMemoryProjectionV1, **changes: object) -> OnlyNoveltyDecisionRequestV1:
    selector = _semantic_query(projection, dataset=DATASET).exact_selector
    values = {
        "command_id": COMMAND,
        "policy_id": "default-novelty",
        "policy_version": "1",
        "evaluation_selector": selector,
    }
    values.update(changes)
    return OnlyNoveltyDecisionRequestV1(**values)  # type: ignore[arg-type]


def _authorities(tmp_path, projection=None, *, novelty_policy=None):  # type: ignore[no-untyped-def]
    revisions, projection = _store(tmp_path, projection)
    policies = OnlyNoveltyPolicyStore(tmp_path)
    policies.put(novelty_policy or policy())
    decisions = OnlyNoveltyDecisionAuthority(tmp_path)
    return revisions, projection, policies, decisions


def _request_v2(subject: OnlyExactEvaluationIntentSubjectV1) -> OnlyNoveltyDecisionRequestV2:
    return OnlyNoveltyDecisionRequestV2(COMMAND, "default-novelty", "1", subject)


def _projection_for_subject(
    projection: OnlyExperimentMemoryProjectionV1, subject: OnlyExactEvaluationIntentSubjectV1
) -> OnlyExperimentMemoryProjectionV1:
    record = next(item for item in projection.records if item.kind == "EvaluationProjectionRecord")
    facets = json.loads(only_canonical_json(record.facets))
    facets.update(
        {
            "graph_fingerprint": subject.graph_fingerprint,
            "candidate_node_fingerprint": subject.candidate_node_fingerprint,
            "output_name": subject.output_name,
            "candidate_fingerprint": subject.candidate_fingerprint,
            "dataset_snapshot_fingerprint": subject.dataset_snapshot_fingerprint,
            "research_result_locator": subject.result_plan_fingerprint,
            "statistics_references": [
                {"statistics_fingerprint": fingerprint, "statistics_result_fingerprint": "0" * 64}
                for fingerprint in subject.statistics_fingerprints
            ],
        }
    )
    closures = facets["run_evaluation_closures"]
    assert isinstance(closures, list)
    first = closures[0]
    assert isinstance(first, dict)
    first.update(
        {
            "specification_fingerprint": subject.specification_fingerprint,
            "catalog_generation_fingerprint": subject.catalog_generation_fingerprint,
            "runtime_generation_fingerprint": subject.runtime_generation_fingerprint,
            "authoring_generation_fingerprint": subject.authoring_generation_fingerprint,
        }
    )
    refs = tuple(
        replace(
            ref,
            locator=subject.result_plan_fingerprint,
            identity=RESULT,
            content_fingerprint=RESULT,
        )
        if ref.source_family == "RESEARCH_RESULT"
        else ref
        for ref in record.source_refs
    )
    changed = OnlyMemoryProjectionRecordV1(record.kind, facets, refs)
    records = tuple(
        sorted(
            (changed if item is record else item for item in projection.records),
            key=lambda item: only_canonical_json(item.to_dict()),
        )
    )
    return OnlyExperimentMemoryProjectionV1(projection.source_manifest, records)


def test_prospective_intent_reaches_novelty_decision_from_real_resolver(tmp_path) -> None:  # type: ignore[no-untyped-def]
    subject = _resolve(_scientific())
    projection = _projection_for_subject(_projection(), subject)
    revisions, projection, policies, decisions = _authorities(tmp_path, projection)

    bundle = decisions.seal_from_request(_request_v2(subject), projection.revision_fingerprint, revisions, policies)
    assert isinstance(bundle, OnlyNoveltyDecisionBundleV2)
    assert bundle.decision.derived_policy_condition is OnlyNoveltyPolicyCondition.EXACT_COMPLETED_EVALUATION
    assert bundle.witness.proofs[0].query["query_kind"] == "EVALUATION_INTENT_EXACT"
    assert "research_result_fingerprint" not in bundle.witness.proofs[0].query["exact_selector"]
    assert bundle.witness.proofs[0].proof["ordered_matches"]
    assert decisions.load_exact(COMMAND) == bundle


def test_prospective_intent_reaches_certified_absence_decision(tmp_path) -> None:  # type: ignore[no-untyped-def]
    subject = _resolve(_scientific())
    projection = _projection(include_evaluation=False)
    revisions, projection, policies, decisions = _authorities(tmp_path, projection)

    bundle = decisions.seal_from_request(_request_v2(subject), projection.revision_fingerprint, revisions, policies)
    assert isinstance(bundle, OnlyNoveltyDecisionBundleV2)
    assert bundle.decision.derived_policy_condition is OnlyNoveltyPolicyCondition.CERTIFIED_NO_MATCH


def test_prospective_decision_request_is_versioned_and_round_trips_without_result_refs() -> None:
    request = _request_v2(_intent_subject())
    payload = request.to_dict()
    encoded = only_canonical_json(payload)
    assert "research_result_fingerprint" not in encoded
    assert "statistics_result_fingerprint" not in encoded
    assert OnlyNoveltyDecisionRequestV2.from_dict(payload) == request


@pytest.mark.parametrize(
    "mutation",
    (
        lambda payload: payload.update(schema_version=2.0),
        lambda payload: payload.update(command_id=1),
        lambda payload: payload.update(policy_id=1),
        lambda payload: payload["evaluation_subject"].update(schema_version=True),
        lambda payload: payload.update(research_result_fingerprint="0" * 64),
    ),
)
def test_prospective_decision_request_v2_rejects_noncanonical_or_result_bound_input(mutation) -> None:  # type: ignore[no-untyped-def]
    payload = json.loads(only_canonical_json(_request_v2(_intent_subject()).to_dict()))
    mutation(payload)
    with pytest.raises(OnlyNoveltyDecisionError):
        OnlyNoveltyDecisionRequestV2.from_dict(payload)


def test_prospective_decision_incomplete_history_fails_closed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    projection = _projection(incomplete=True)
    revisions, projection, policies, decisions = _authorities(tmp_path, projection)
    bundle = decisions.seal_from_request(
        _request_v2(_intent_subject()), projection.revision_fingerprint, revisions, policies
    )
    assert bundle.decision.derived_policy_condition is OnlyNoveltyPolicyCondition.PROOF_INCOMPLETE
    assert bundle.decision.outcome is OnlyNoveltyPolicyOutcome.FAIL_CLOSED


def test_prospective_decision_unavailable_history_fails_closed(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    revisions, projection, policies, decisions = _authorities(tmp_path)

    def unavailable(_revisions, query):  # type: ignore[no-untyped-def]
        return OnlyMemoryHistoricalProofV1(
            query.query_fingerprint,
            query.projection_revision_fingerprint,
            projection.logical_digest,
            projection.source_manifest.manifest_fingerprint,
            OnlyMemoryHistoricalProofStatus.PROOF_UNAVAILABLE,
            (),
            "SOURCE_OBSERVATION_UNAVAILABLE",
        )

    monkeypatch.setattr("onlyalpha.research.novelty.decision.only_query_experiment_memory_history", unavailable)
    bundle = decisions.seal_from_request(
        _request_v2(_intent_subject()), projection.revision_fingerprint, revisions, policies
    )
    assert bundle.decision.derived_policy_condition is OnlyNoveltyPolicyCondition.PROOF_UNAVAILABLE
    assert bundle.decision.outcome is OnlyNoveltyPolicyOutcome.FAIL_CLOSED


def test_prospective_same_command_changed_subject_conflicts(tmp_path) -> None:  # type: ignore[no-untyped-def]
    revisions, projection, policies, decisions = _authorities(tmp_path)
    request = _request_v2(_intent_subject())
    decisions.seal_from_request(request, projection.revision_fingerprint, revisions, policies)
    with pytest.raises(OnlyNoveltyDecisionConflictError):
        decisions.seal_from_request(
            _request_v2(replace(_intent_subject(), dataset_snapshot_fingerprint="0" * 64)),
            projection.revision_fingerprint,
            revisions,
            policies,
        )


def test_exact_evaluation_and_replication_policy_are_deterministic(tmp_path) -> None:  # type: ignore[no-untyped-def]
    revisions, projection, policies, decisions = _authorities(tmp_path)
    first = decisions.seal_from_request(_request(projection), projection.revision_fingerprint, revisions, policies)
    assert first.decision.derived_policy_condition is OnlyNoveltyPolicyCondition.EXACT_COMPLETED_EVALUATION
    assert first.decision.outcome is OnlyNoveltyPolicyOutcome.REUSE
    assert first.decision.reason_codes == (OnlyNoveltyDecisionReason.EXACT_EVALUATION_MATCH,)
    assert first == decisions.seal_from_request(
        _request(projection), projection.revision_fingerprint, revisions, policies
    )

    other_root = tmp_path / "replication"
    replication = policy(EXACT_COMPLETED_EVALUATION=OnlyNoveltyPolicyOutcome.ADMIT)
    other_revisions, other_projection, other_policies, other_decisions = _authorities(
        other_root, novelty_policy=replication
    )
    decision = other_decisions.seal_from_request(
        _request(other_projection), other_projection.revision_fingerprint, other_revisions, other_policies
    )
    assert decision.decision.outcome is OnlyNoveltyPolicyOutcome.ADMIT


def test_forged_condition_cannot_enter_decision_authority(tmp_path) -> None:  # type: ignore[no-untyped-def]
    revisions, projection, policies, decisions = _authorities(tmp_path / "source")
    bundle = decisions.seal_from_request(_request(projection), projection.revision_fingerprint, revisions, policies)
    forged = replace(
        bundle,
        decision=replace(
            bundle.decision,
            derived_policy_condition=OnlyNoveltyPolicyCondition.CERTIFIED_NO_MATCH,
            outcome=OnlyNoveltyPolicyOutcome.ADMIT,
            reason_codes=(OnlyNoveltyDecisionReason.CERTIFIED_EVALUATION_ABSENCE,),
        ),
    )
    assert forged.decision.decision_fingerprint != bundle.decision.decision_fingerprint
    assert type(forged.decision).from_dict(forged.decision.to_dict(), forged.witness.subject) == forged.decision
    target = OnlyNoveltyDecisionAuthority(tmp_path / "forged-condition")
    with pytest.raises(OnlyNoveltyDecisionCorruptError, match="Decision request"):
        target.seal_from_request(  # type: ignore[arg-type]
            forged, projection.revision_fingerprint, revisions, policies
        )
    with pytest.raises(OnlyNoveltyDecisionNotFoundError):
        target.load_exact(COMMAND)


def test_forged_outcome_cannot_enter_decision_authority(tmp_path) -> None:  # type: ignore[no-untyped-def]
    revisions, projection, policies, decisions = _authorities(tmp_path / "source")
    bundle = decisions.seal_from_request(_request(projection), projection.revision_fingerprint, revisions, policies)
    forged = replace(bundle, decision=replace(bundle.decision, outcome=OnlyNoveltyPolicyOutcome.ADMIT))
    assert forged.decision.decision_fingerprint != bundle.decision.decision_fingerprint
    assert type(forged.decision).from_dict(forged.decision.to_dict(), forged.witness.subject) == forged.decision
    target = OnlyNoveltyDecisionAuthority(tmp_path / "forged-outcome")
    with pytest.raises(OnlyNoveltyDecisionCorruptError, match="Decision request"):
        target.seal_from_request(  # type: ignore[arg-type]
            forged, projection.revision_fingerprint, revisions, policies
        )
    with pytest.raises(OnlyNoveltyDecisionNotFoundError):
        target.load_exact(COMMAND)


def test_absence_incomplete_operational_and_stop_conditions(tmp_path) -> None:  # type: ignore[no-untyped-def]
    absent = _projection(include_evaluation=False)
    revisions, absent, policies, decisions = _authorities(tmp_path / "absent", absent)
    decision = decisions.seal_from_request(_request(absent), absent.revision_fingerprint, revisions, policies)
    assert decision.decision.derived_policy_condition is OnlyNoveltyPolicyCondition.CERTIFIED_NO_MATCH
    assert decision.decision.outcome is OnlyNoveltyPolicyOutcome.ADMIT

    incomplete = _projection(incomplete=True)
    revisions, incomplete, policies, decisions = _authorities(tmp_path / "incomplete", incomplete)
    decision = decisions.seal_from_request(_request(incomplete), incomplete.revision_fingerprint, revisions, policies)
    assert decision.decision.derived_policy_condition is OnlyNoveltyPolicyCondition.PROOF_INCOMPLETE
    assert decision.decision.outcome is OnlyNoveltyPolicyOutcome.FAIL_CLOSED

    no_match_selector = replace(_request(absent).evaluation_selector, dataset_snapshot_fingerprint="9" * 64)
    failed = OnlyExactFailureEvidenceSelectorV1(
        "OPERATIONAL_FAILURE", "ARTIFACT_COMMIT_FAILED", OnlyResearchRunTerminalOwnerV1(FAILED_RUN_ID, 2)
    )
    revisions, absent, policies, decisions = _authorities(tmp_path / "operational", absent)
    operational = decisions.seal_from_request(
        _request(absent, evaluation_selector=no_match_selector, related_failures=(failed,)),
        absent.revision_fingerprint,
        revisions,
        policies,
    )
    assert operational.decision.derived_policy_condition is OnlyNoveltyPolicyCondition.OPERATIONAL_FAILURE
    assert operational.decision.outcome is not OnlyNoveltyPolicyOutcome.SUPPRESS

    base = _projection(include_evaluation=False)
    cut = next(item for item in base.source_manifest.cuts if item.source_family == "SEARCH_PROVENANCE")
    identity = "7" * 64
    record = OnlyMemoryProjectionRecordV1(
        "FailureEvidenceProjectionRecord",
        {
            "owner_kind": "SEARCH_OCCURRENCE",
            "classification": "SEARCH_OR_BUDGET_STOP",
            "failure_code": "SEARCH_BUDGET_EXHAUSTED",
            "iteration_result_fingerprint": identity,
        },
        (
            OnlyMemorySourceRefV1(
                "SEARCH_PROVENANCE", cut.cut_fingerprint, f"iteration-results/{identity}", identity, identity
            ),
        ),
    )
    projection = OnlyExperimentMemoryProjectionV1(
        base.source_manifest,
        tuple(sorted((*base.records, record), key=lambda item: only_canonical_json(item.to_dict()))),
    )
    revisions, projection, policies, decisions = _authorities(tmp_path / "stop", projection)
    stop = OnlyExactFailureEvidenceSelectorV1(
        "SEARCH_OR_BUDGET_STOP", "SEARCH_BUDGET_EXHAUSTED", OnlySearchFailureOwnerV1(identity)
    )
    decision = decisions.seal_from_request(
        _request(projection, evaluation_selector=no_match_selector, related_failures=(stop,)),
        projection.revision_fingerprint,
        revisions,
        policies,
    )
    assert decision.decision.derived_policy_condition is OnlyNoveltyPolicyCondition.SEARCH_OR_BUDGET_STOP
    assert decision.decision.outcome is not OnlyNoveltyPolicyOutcome.SUPPRESS


class _DecisionReader:
    def __init__(self, value: OnlyQualificationDecision) -> None:
        self.value = value

    def load_verified(self, fingerprint: str) -> OnlyQualificationDecision:
        if fingerprint != self.value.decision_fingerprint:
            raise ValueError("missing")
        return self.value


class _RelationReader:
    def __init__(self, value: OnlyStrategyFreezeRelation) -> None:
        self.value = value

    def load_freeze_relation(self, fingerprint: str) -> OnlyStrategyFreezeRelation:
        if fingerprint != self.value.relation_fingerprint:
            raise ValueError("missing")
        return self.value


def _negative_authorities():
    relation = OnlyStrategyFreezeRelation("6" * 64, CANDIDATE, RESULT, ("7" * 64,), "8" * 64, ("9" * 64,))
    evidence = OnlyQualificationEvidenceReference(
        OnlyQualificationEvidenceKind.RESEARCH_RESULT, RESULT, PLAN, relation.relation_fingerprint
    )
    criterion = OnlyQualificationCriterionResult(
        "minimum-effect", RESULT, "IC_MEAN", Decimal("0"), ">", Decimal("0.01"), OnlyQualificationCriterionOutcome.FAIL
    )
    decision = OnlyQualificationDecision(
        relation.strategy_fingerprint,
        OnlyQualificationGate.RESEARCH_TO_BACKTEST,
        "qualification-policy",
        "1",
        "a" * 64,
        (evidence,),
        (criterion,),
        OnlyQualificationOutcome.REJECTED,
    )
    return decision, relation


def _with_qualification(projection: OnlyExperimentMemoryProjectionV1, decision: OnlyQualificationDecision):
    cut = next(item for item in projection.source_manifest.cuts if item.source_family == "QUALIFICATION_DECISION")
    ref = OnlyMemorySourceRefV1(
        "QUALIFICATION_DECISION",
        cut.cut_fingerprint,
        decision.decision_fingerprint,
        decision.decision_fingerprint,
        decision.decision_fingerprint,
    )
    record = OnlyMemoryProjectionRecordV1(
        "FailureEvidenceProjectionRecord",
        {
            "owner_kind": "QUALIFICATION_DECISION",
            "classification": "QUALIFICATION_REJECT",
            "subject_strategy_fingerprint": decision.subject_strategy_fingerprint,
            "policy_id": decision.policy_id,
            "policy_version": decision.policy_version,
            "policy_fingerprint": decision.policy_fingerprint,
            "evidence_refs": [item.to_dict() for item in decision.evidence],
        },
        (ref,),
    )
    return OnlyExperimentMemoryProjectionV1(
        projection.source_manifest,
        tuple(sorted((*projection.records, record), key=lambda item: only_canonical_json(item.to_dict()))),
    )


def test_exact_negative_evidence_requires_complete_exact_relation(tmp_path) -> None:  # type: ignore[no-untyped-def]
    qualification, relation = _negative_authorities()
    projection = _with_qualification(_projection(), qualification)
    revisions, projection, policies, decisions = _authorities(tmp_path, projection)
    binding = OnlyNoveltyQualificationBindingV1(
        qualification.decision_fingerprint,
        qualification.policy_id,
        qualification.policy_version,
        qualification.policy_fingerprint,
    )
    bundle = decisions.seal_from_request(
        _request(projection, qualification_binding=binding),
        projection.revision_fingerprint,
        revisions,
        policies,
        qualification_decisions=_DecisionReader(qualification),
        freeze_relations=_RelationReader(relation),
    )
    assert bundle.decision.derived_policy_condition is OnlyNoveltyPolicyCondition.EXACT_COMPLETED_NEGATIVE_EVIDENCE
    assert bundle.decision.outcome is OnlyNoveltyPolicyOutcome.SUPPRESS

    for index, (wrong_binding, wrong_relation) in enumerate(
        (
            (replace(binding, policy_fingerprint="b" * 64), relation),
            (binding, replace(relation, candidate_fingerprint="b" * 64)),
            (binding, replace(relation, research_result_fingerprint="c" * 64)),
        )
    ):
        changed_authority = OnlyNoveltyDecisionAuthority(tmp_path / str(index))
        changed = changed_authority.seal_from_request(
            _request(projection, qualification_binding=wrong_binding),
            projection.revision_fingerprint,
            revisions,
            policies,
            qualification_decisions=_DecisionReader(qualification),
            freeze_relations=_RelationReader(wrong_relation),
        )
        assert changed.decision.derived_policy_condition is OnlyNoveltyPolicyCondition.PROOF_UNAVAILABLE
        assert changed.decision.outcome is OnlyNoveltyPolicyOutcome.FAIL_CLOSED


def test_qualification_match_without_exact_evaluation_is_incomplete(tmp_path) -> None:  # type: ignore[no-untyped-def]
    qualification, relation = _negative_authorities()
    projection = _with_qualification(_projection(include_evaluation=False), qualification)
    revisions, projection, policies, decisions = _authorities(tmp_path, projection)
    binding = OnlyNoveltyQualificationBindingV1(
        qualification.decision_fingerprint,
        qualification.policy_id,
        qualification.policy_version,
        qualification.policy_fingerprint,
    )
    bundle = decisions.seal_from_request(
        _request(projection, qualification_binding=binding),
        projection.revision_fingerprint,
        revisions,
        policies,
        qualification_decisions=_DecisionReader(qualification),
        freeze_relations=_RelationReader(relation),
    )
    assert bundle.decision.derived_policy_condition is OnlyNoveltyPolicyCondition.PROOF_INCOMPLETE
    assert bundle.decision.outcome is OnlyNoveltyPolicyOutcome.FAIL_CLOSED


def test_same_command_changed_intent_conflicts_and_memory_growth_retry_returns_original(tmp_path) -> None:  # type: ignore[no-untyped-def]
    revisions, projection, policies, decisions = _authorities(tmp_path)
    request = _request(projection)
    original = decisions.seal_from_request(request, projection.revision_fingerprint, revisions, policies)
    grown = _projection(include_evaluation=False)
    revisions._publish_and_activate(grown)
    assert decisions.seal_from_request(request, grown.revision_fingerprint, revisions, policies) == original
    changed = replace(
        request, evaluation_selector=replace(request.evaluation_selector, dataset_snapshot_fingerprint="9" * 64)
    )
    with pytest.raises(OnlyNoveltyDecisionConflictError):
        decisions.seal_from_request(changed, grown.revision_fingerprint, revisions, policies)


def test_intent_and_subject_identity_bind_every_exact_semantic_dimension() -> None:
    projection = _projection()
    request = _request(projection)
    selector = request.evaluation_selector
    semantic = selector.semantic
    variants = (
        replace(request, policy_version="2"),
        replace(request, evaluation_selector=replace(selector, semantic=replace(semantic, graph_fingerprint="0" * 64))),
        replace(
            request,
            evaluation_selector=replace(selector, semantic=replace(semantic, candidate_node_fingerprint="0" * 64)),
        ),
        replace(request, evaluation_selector=replace(selector, semantic=replace(semantic, output_name="other"))),
        replace(request, evaluation_selector=replace(selector, candidate_fingerprint="0" * 64)),
        replace(request, evaluation_selector=replace(selector, dataset_snapshot_fingerprint="0" * 64)),
        replace(request, evaluation_selector=replace(selector, specification_fingerprint="0" * 64)),
        replace(request, evaluation_selector=replace(selector, result_plan_fingerprint="0" * 64)),
        replace(request, evaluation_selector=replace(selector, catalog_generation_fingerprint="0" * 64)),
        replace(request, evaluation_selector=replace(selector, runtime_generation_fingerprint="0" * 64)),
        replace(request, evaluation_selector=replace(selector, authoring_generation_fingerprint="0" * 64)),
        replace(
            request,
            evaluation_selector=replace(
                selector,
                statistics_references=(
                    replace(selector.statistics_references[0], statistics_result_fingerprint="1" * 64),
                ),
            ),
        ),
        replace(request, evaluation_selector=replace(selector, search_experiment_fingerprint="0" * 64)),
    )
    assert (
        len({request.canonical_intent_fingerprint, *(item.canonical_intent_fingerprint for item in variants)})
        == len(variants) + 1
    )


def test_subject_and_witness_freeze_nested_input_mappings(tmp_path) -> None:  # type: ignore[no-untyped-def]
    revisions, projection, policies, decisions = _authorities(tmp_path)
    bundle = decisions.seal_from_request(_request(projection), projection.revision_fingerprint, revisions, policies)
    subject_before = bundle.witness.subject.subject_fingerprint
    witness_before = bundle.witness.witness_fingerprint
    resolved = bundle.witness.subject.resolved_subject
    proof = bundle.witness.proofs[0].proof
    assert isinstance(resolved, dict) and isinstance(proof, dict)
    resolved["subject_type"] = "MUTATED"
    proof["proof_status"] = "MUTATED"
    assert bundle.witness.subject.subject_fingerprint == subject_before
    assert bundle.witness.witness_fingerprint == witness_before


def test_witness_rejects_historical_proof_for_another_exact_subject(tmp_path) -> None:  # type: ignore[no-untyped-def]
    revisions, projection, policies, decisions = _authorities(tmp_path)
    bundle = decisions.seal_from_request(_request(projection), projection.revision_fingerprint, revisions, policies)
    resolved = dict(bundle.witness.subject.resolved_subject)
    selector = dict(resolved["evaluation_selector"])  # type: ignore[arg-type]
    selector["candidate_fingerprint"] = "0" * 64
    resolved["evaluation_selector"] = selector
    intent = _request(
        projection,
        evaluation_selector=replace(_request(projection).evaluation_selector, candidate_fingerprint="0" * 64),
    )
    subject = type(bundle.witness.subject)(COMMAND.value, intent.canonical_intent_fingerprint, resolved)
    with pytest.raises(OnlyNoveltyWitnessCorruptError, match="exact Decision subject"):
        replace(bundle.witness, subject=subject)


def test_concurrent_same_command_converges_with_barrier(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    revisions, projection, policies, decisions = _authorities(tmp_path)
    barrier = Barrier(2)

    put_verified = decisions._put_verified_bundle

    def barrier_put(bundle):  # type: ignore[no-untyped-def]
        barrier.wait()
        return put_verified(bundle)

    monkeypatch.setattr(decisions, "_put_verified_bundle", barrier_put)

    def evaluate():
        return decisions.seal_from_request(_request(projection), projection.revision_fingerprint, revisions, policies)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _: evaluate(), range(2)))
    assert results[0] == results[1]
    assert decisions.load_exact(COMMAND) == results[0]


class _CutReader:
    def __init__(self, cut: OnlySourceClosedCutV1, *, available: bool = True) -> None:
        self.cut = cut
        self.available = available

    def load_closed_cut_verified(self, fingerprint: str) -> OnlySourceClosedCutV1:
        if not self.available or fingerprint != self.cut.cut_fingerprint:
            raise ValueError("unavailable")
        return self.cut

    def iter_closed_cut_observations_verified(self, fingerprint: str):  # type: ignore[no-untyped-def]
        self.load_closed_cut_verified(fingerprint)
        return ()


def test_historical_replay_uses_frozen_empty_cut_not_active_memory(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    empty = _projection(include_evaluation=False)
    empty = OnlyExperimentMemoryProjectionV1(empty.source_manifest, ())
    revisions, empty, policies, decisions = _authorities(tmp_path, empty)
    bundle = decisions.seal_from_request(_request(empty), empty.revision_fingerprint, revisions, policies)
    cuts = {family: OnlySourceClosedCutV1(family, 1, ()) for family in MANDATORY_FAMILIES}
    readers = {family: _CutReader(cut) for family, cut in cuts.items()}
    monkeypatch.setattr(
        "onlyalpha.research.novelty.decision.only_query_experiment_memory_history",
        lambda *_: (_ for _ in ()).throw(AssertionError("historical replay queried Memory")),
    )
    assert only_verify_historical_novelty_decision(bundle, policies, readers) == bundle.decision
    revisions._publish_and_activate(_projection())
    assert only_verify_historical_novelty_decision(bundle, policies, readers) == bundle.decision
    readers[MANDATORY_FAMILIES[0]].available = False
    with pytest.raises((OnlyHistoricalProofUnavailableError, ValueError)):
        only_verify_historical_novelty_decision(bundle, policies, readers)


def test_prospective_v2_decision_replays_frozen_absence_without_requery(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    empty = _projection(include_evaluation=False)
    revisions, empty, policies, decisions = _authorities(tmp_path, empty)
    bundle = decisions.seal_from_request(
        _request_v2(_intent_subject()), empty.revision_fingerprint, revisions, policies
    )
    cuts = {family: OnlySourceClosedCutV1(family, 1, ()) for family in MANDATORY_FAMILIES}
    readers = {family: _CutReader(cut) for family, cut in cuts.items()}
    monkeypatch.setattr(
        "onlyalpha.research.novelty.decision.only_query_experiment_memory_history",
        lambda *_: (_ for _ in ()).throw(AssertionError("historical replay queried Memory")),
    )
    assert only_verify_historical_novelty_decision(bundle, policies, readers) == bundle.decision


def test_prospective_v2_witness_rejects_mutated_nested_subject(tmp_path) -> None:  # type: ignore[no-untyped-def]
    subject = _intent_subject()
    request = _request_v2(subject)
    revisions, projection, policies, decisions = _authorities(tmp_path)
    decisions.seal_from_request(request, projection.revision_fingerprint, revisions, policies)
    path = tmp_path / "research" / "novelty-decisions" / COMMAND.value / "bundle.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    resolved = payload["witness"]["subject"]["resolved_subject"]
    resolved_subject = dict(resolved["evaluation_subject"])
    assert isinstance(resolved_subject, dict)
    resolved_subject["dataset_snapshot_fingerprint"] = "0" * 64
    resolved["evaluation_subject"] = resolved_subject
    path.write_text(only_canonical_json(payload), encoding="utf-8")
    with pytest.raises((OnlyNoveltyDecisionError, OnlyNoveltyDecisionCorruptError, OnlyNoveltyWitnessCorruptError)):
        decisions.load_exact(COMMAND)


@pytest.mark.parametrize("target", ["decision", "witness", "policy", "source", "proof-order"])
def test_bundle_semantic_mutation_fails_closed(tmp_path, target: str) -> None:  # type: ignore[no-untyped-def]
    revisions, projection, policies, decisions = _authorities(tmp_path)
    decisions.seal_from_request(_request(projection), projection.revision_fingerprint, revisions, policies)
    path = tmp_path / "research" / "novelty-decisions" / COMMAND.value / "bundle.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if target == "decision":
        payload["decision"]["outcome"] = "ADMIT"
    elif target == "witness":
        payload["witness"]["projection_logical_digest"] = "0" * 64
    elif target == "policy":
        payload["decision"]["policy_fingerprint"] = "0" * 64
    elif target == "source":
        payload["witness"]["source_manifest"]["manifest_fingerprint"] = "0" * 64
    else:
        payload["decision"]["ordered_proof_references"][0] = "0" * 64
    path.write_text(only_canonical_json(payload), encoding="utf-8")
    with pytest.raises((OnlyNoveltyDecisionCorruptError, OnlyNoveltyWitnessCorruptError)):
        decisions.load_exact(COMMAND)


@pytest.mark.parametrize("member", ["decision", "witness"])
def test_unsupported_bundle_schema_and_publish_crash_are_explicit(tmp_path, monkeypatch, member: str) -> None:  # type: ignore[no-untyped-def]
    revisions, projection, policies, decisions = _authorities(tmp_path)
    decisions.seal_from_request(_request(projection), projection.revision_fingerprint, revisions, policies)
    path = tmp_path / "research" / "novelty-decisions" / COMMAND.value / "bundle.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[member]["schema_version"] = 2
    path.write_text(only_canonical_json(payload), encoding="utf-8")
    expected = (
        OnlyNoveltyWitnessSchemaUnsupportedError if member == "witness" else OnlyNoveltyDecisionSchemaUnsupportedError
    )
    with pytest.raises(expected):
        decisions.load_exact(COMMAND)

    crash_root = tmp_path / "crash"
    crash = OnlyNoveltyDecisionAuthority(crash_root)
    monkeypatch.setattr(os, "rename", lambda *_: (_ for _ in ()).throw(OSError("crash")))
    with pytest.raises(OnlyNoveltyDecisionCorruptError):
        crash.seal_from_request(_request(projection), projection.revision_fingerprint, revisions, policies)
    with pytest.raises(OnlyNoveltyDecisionNotFoundError):
        crash.load_exact(COMMAND)


def test_authoritative_api_does_not_accept_condition_or_outcome() -> None:
    parameters = inspect.signature(OnlyNoveltyDecisionAuthority.seal_from_request).parameters
    assert "condition" not in parameters
    assert "outcome" not in parameters
    assert "decision" not in parameters
    assert "witness" not in parameters
    assert "bundle" not in parameters
    assert "canonical_intent_fingerprint" not in inspect.signature(OnlyNoveltyDecisionRequestV1).parameters
