"""Exact history query identity, proof-state and revision-isolation tests."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.memory.projector import (
    OnlyExperimentMemoryProjectionV1,
    OnlyMemoryProjectionRecordV1,
    OnlyMemorySourceRefV1,
)
from onlyalpha.research.memory.query import (
    OnlyAgentFailureOwnerV1,
    OnlyExactEvaluationHistorySelectorV1,
    OnlyExactFailureEvidenceSelectorV1,
    OnlyExactParameterObservationSelectorV1,
    OnlyExactSemanticHistorySelectorV1,
    OnlyExactStatisticsReferenceV1,
    OnlyMemoryHistoricalProofStatus,
    OnlyMemoryHistoricalQueryV1,
    OnlyQualificationFailureOwnerV1,
    OnlyResearchRunFailureOwnerV1,
    OnlyResearchRunTerminalOwnerV1,
    OnlySearchFailureOwnerV1,
    only_query_experiment_memory_history,
)
from onlyalpha.research.memory.source_manifest import MANDATORY_FAMILIES, OnlyExperimentMemorySourceCutManifestV1
from onlyalpha.research.memory.store import OnlyExperimentMemoryRevisionStore
from onlyalpha.research.source_cut import OnlySourceClosedCutV1

GRAPH, NODE, CANDIDATE = "a" * 64, "b" * 64, "c" * 64
DATASET, SPECIFICATION, PLAN, RESULT = "d" * 64, "e" * 64, "f" * 64, "1" * 64
CATALOG, RUNTIME, AUTHORING, STATISTICS = "2" * 64, "3" * 64, "4" * 64, "5" * 64
EXPERIMENT, SPACE, PROPOSAL, FAILURE = "6" * 64, "7" * 64, "8" * 64, "9" * 64
STATISTICS_RESULT, OTHER_STATISTICS_RESULT = "0" * 64, "f" * 64
COMPLETED_RUN_ID = "00000000-0000-4000-8000-000000000001"
FAILED_RUN_ID = "00000000-0000-4000-8000-000000000002"
ASSIGNMENT = [{"target": "window", "value": 20}]


def _projection(
    *, duplicate: bool = False, incomplete: bool = False, include_evaluation: bool = True
) -> OnlyExperimentMemoryProjectionV1:
    cuts = {family: OnlySourceClosedCutV1(family, 1, ()) for family in MANDATORY_FAMILIES}
    manifest = OnlyExperimentMemorySourceCutManifestV1.from_cuts(tuple(cuts.values()))

    def ref(family: str, identity: str) -> OnlyMemorySourceRefV1:
        return OnlyMemorySourceRefV1(family, cuts[family].cut_fingerprint, identity, identity, identity)

    run_ref = ref("RESEARCH_RUN", FAILURE)
    search_refs = {
        name: ref(family, identity).to_dict()
        for name, family, identity in (
            ("experiment_source_ref", "SEARCH_PROVENANCE", EXPERIMENT),
            ("plan_source_ref", "SEARCH_PROVENANCE", PROPOSAL),
            ("admission_source_ref", "PRODUCT_COMMAND_ADMISSION", "a" * 64),
            ("receipt_source_ref", "PRODUCT_COMMAND_RECEIPT", "b" * 64),
        )
    }
    search_lineage = {
        "search_method": "PARAMETER",
        "experiment_fingerprint": EXPERIMENT,
        "iteration_plan_fingerprint": PROPOSAL,
        "iteration_result_fingerprint": None,
        "research_product_command_id": "00000000-0000-4000-8000-000000000003",
        "research_product_command_kind": "CREATE_RESEARCH_RUN",
        "research_product_command_fingerprint": "c" * 64,
        **search_refs,
        "iteration_result_source_ref": None,
    }

    semantic = {
        "candidate_fingerprint": CANDIDATE,
        "graph_fingerprint": GRAPH,
        "candidate_node_fingerprint": NODE,
        "output_name": "factor_value",
        "dataset_snapshot_fingerprint": DATASET,
        "research_result_locator": PLAN,
        "research_result_fingerprint": RESULT,
        "statistics_references": [
            {"statistics_fingerprint": STATISTICS, "statistics_result_fingerprint": STATISTICS_RESULT}
        ],
        "run_evaluation_closures": [
            {
                "run_id": COMPLETED_RUN_ID,
                "run_revision": 2,
                "run_state": "COMPLETED",
                "specification_fingerprint": SPECIFICATION,
                "research_result_fingerprint": RESULT,
                "artifact_content_fingerprint": "a" * 64,
                "catalog_generation_fingerprint": CATALOG,
                "runtime_generation_fingerprint": RUNTIME,
                "authoring_generation_fingerprint": AUTHORING,
                "calculation_execution_evidence_fingerprints": ["b" * 64],
                "run_source_ref": ref("RESEARCH_RUN", "d" * 64).to_dict(),
                "search_lineage": search_lineage,
            },
            {
                "run_id": FAILED_RUN_ID,
                "run_revision": 2,
                "run_state": "FAILED",
                "specification_fingerprint": "c" * 64,
                "research_result_fingerprint": RESULT,
                "artifact_content_fingerprint": None,
                "catalog_generation_fingerprint": "d" * 64,
                "runtime_generation_fingerprint": "e" * 64,
                "authoring_generation_fingerprint": None,
                "calculation_execution_evidence_fingerprints": [],
                "run_source_ref": run_ref.to_dict(),
                "search_lineage": None,
            },
        ],
    }
    if incomplete:
        semantic.pop("output_name")
    evaluation = OnlyMemoryProjectionRecordV1("EvaluationProjectionRecord", semantic, (ref("RESEARCH_RESULT", RESULT),))
    parameter = OnlyMemoryProjectionRecordV1(
        "ParameterObservationProjectionRecord",
        {
            "experiment_fingerprint": EXPERIMENT,
            "search_space_fingerprint": SPACE,
            "proposal_fingerprint": PROPOSAL,
            "normalized_assignment": ASSIGNMENT,
            "grid_ordinal": 2,
            "status": "COMPLETED_EVIDENCE",
        },
        (ref("SEARCH_PROVENANCE", PROPOSAL),),
    )
    failure = OnlyMemoryProjectionRecordV1(
        "FailureEvidenceProjectionRecord",
        {
            "classification": "OPERATIONAL_FAILURE",
            "failure_code": "ARTIFACT_COMMIT_FAILED",
            "run_context": {
                "run_id": FAILED_RUN_ID,
                "run_revision": 2,
                "run_state": "FAILED",
                "specification_fingerprint": "c" * 64,
                "research_result_fingerprint": RESULT,
                "artifact_content_fingerprint": None,
                "catalog_generation_fingerprint": "d" * 64,
                "runtime_generation_fingerprint": "e" * 64,
                "authoring_generation_fingerprint": None,
                "calculation_execution_evidence_fingerprints": [],
                "run_source_ref": run_ref.to_dict(),
                "search_lineage": search_lineage,
            },
            "failure_phase": "ARTIFACT_COMMIT",
            "failure_detail": "artifact unavailable",
        },
        (run_ref, *tuple(OnlyMemorySourceRefV1(**value) for value in search_refs.values())),
    )
    records = [parameter, failure]
    if include_evaluation:
        records.append(evaluation)
    if duplicate:
        records.append(evaluation)
    records.sort(key=lambda record: only_canonical_json(record.to_dict()))
    return OnlyExperimentMemoryProjectionV1(manifest, tuple(records))


def _store(tmp_path: Path, projection: OnlyExperimentMemoryProjectionV1 | None = None):
    projection = projection or _projection()
    store = OnlyExperimentMemoryRevisionStore(tmp_path / "experiment-memory")
    store._publish_and_activate(projection)
    return store, projection


def _replace_record_facets(
    projection: OnlyExperimentMemoryProjectionV1, kind: str, update
) -> OnlyExperimentMemoryProjectionV1:  # type: ignore[no-untyped-def]
    records = list(projection.records)
    index = next(index for index, record in enumerate(records) if record.kind == kind)
    record = records[index]
    facets = json.loads(only_canonical_json(record.facets))
    update(facets)
    records[index] = OnlyMemoryProjectionRecordV1(record.kind, facets, record.source_refs)
    records.sort(key=lambda item: only_canonical_json(item.to_dict()))
    return OnlyExperimentMemoryProjectionV1(projection.source_manifest, tuple(records))


def _source_ref(
    projection: OnlyExperimentMemoryProjectionV1,
    family: str,
    identity: str,
    *,
    locator: str | None = None,
) -> OnlyMemorySourceRefV1:
    cut = next(cut for cut in projection.source_manifest.cuts if cut.source_family == family)
    return OnlyMemorySourceRefV1(family, cut.cut_fingerprint, locator or identity, identity, identity)


def _with_failure_records(
    projection: OnlyExperimentMemoryProjectionV1, *records: OnlyMemoryProjectionRecordV1
) -> OnlyExperimentMemoryProjectionV1:
    retained = [record for record in projection.records if record.kind != "FailureEvidenceProjectionRecord"]
    ordered = tuple(sorted((*retained, *records), key=lambda record: only_canonical_json(record.to_dict())))
    return OnlyExperimentMemoryProjectionV1(projection.source_manifest, ordered)


def _run_terminal_record(
    projection: OnlyExperimentMemoryProjectionV1,
    *,
    run_id: str = FAILED_RUN_ID,
    revision: int = 2,
    state: str = "FAILED",
) -> OnlyMemoryProjectionRecordV1:
    identity = {"FAILED": "9" * 64, "CANCELLED": "a" * 64}[state]
    source = _source_ref(projection, "RESEARCH_RUN", identity)
    structured = state == "FAILED"
    return OnlyMemoryProjectionRecordV1(
        "FailureEvidenceProjectionRecord",
        {
            "classification": "OPERATIONAL_FAILURE",
            "run_context": {
                "run_id": run_id,
                "run_revision": revision,
                "run_state": state,
                "specification_fingerprint": SPECIFICATION,
                "research_result_fingerprint": None,
                "artifact_content_fingerprint": None,
                "catalog_generation_fingerprint": CATALOG,
                "runtime_generation_fingerprint": RUNTIME,
                "authoring_generation_fingerprint": None,
                "calculation_execution_evidence_fingerprints": [],
                "run_source_ref": source.to_dict(),
                "search_lineage": None,
            },
            "failure_phase": "EXECUTION" if structured else None,
            "failure_code": "RESEARCH_EXECUTION_FAILED" if structured else None,
            "failure_detail": "execution failed" if structured else None,
        },
        (source,),
    )


def _search_failure_record(
    projection: OnlyExperimentMemoryProjectionV1, identity: str = "7" * 64
) -> OnlyMemoryProjectionRecordV1:
    source = _source_ref(projection, "SEARCH_PROVENANCE", identity, locator=f"iteration-results/{identity}")
    return OnlyMemoryProjectionRecordV1(
        "FailureEvidenceProjectionRecord",
        {
            "classification": "SEARCH_OR_BUDGET_STOP",
            "failure_code": "SEARCH_BUDGET_EXHAUSTED",
            "iteration_result_fingerprint": identity,
        },
        (source,),
    )


def _agent_failure_record(
    projection: OnlyExperimentMemoryProjectionV1, identity: str = "8" * 64
) -> OnlyMemoryProjectionRecordV1:
    source = _source_ref(projection, "AGENT_PROVENANCE", identity, locator=f"model-calls/results/{identity}")
    return OnlyMemoryProjectionRecordV1(
        "FailureEvidenceProjectionRecord",
        {
            "classification": "OPERATIONAL_FAILURE",
            "failure_code": "AGENT_MODEL_CALL_FAILED",
            "outcome": "FAILED",
        },
        (source,),
    )


def _qualification_failure_record(
    projection: OnlyExperimentMemoryProjectionV1, identity: str = "b" * 64
) -> OnlyMemoryProjectionRecordV1:
    source = _source_ref(projection, "QUALIFICATION_DECISION", identity)
    return OnlyMemoryProjectionRecordV1(
        "FailureEvidenceProjectionRecord",
        {
            "classification": "QUALIFICATION_REJECT",
            "subject_strategy_fingerprint": "c" * 64,
            "policy_id": "policy",
            "policy_version": "1",
            "policy_fingerprint": "d" * 64,
            "evidence_refs": [
                {
                    "kind": "BACKTEST_EVIDENCE",
                    "evidence_fingerprint": "e" * 64,
                    "locator_fingerprint": None,
                    "subject_binding_fingerprint": None,
                }
            ],
        },
        (source,),
    )


def _failure_status(
    tmp_path: Path,
    projection: OnlyExperimentMemoryProjectionV1,
    selector: OnlyExactFailureEvidenceSelectorV1,
) -> OnlyMemoryHistoricalProofStatus:
    store, projection = _store(tmp_path, projection)
    return only_query_experiment_memory_history(
        store, OnlyMemoryHistoricalQueryV1(projection.revision_fingerprint, selector)
    ).proof_status


def _mutate_failure_record(record, update, *, source_refs=None):  # type: ignore[no-untyped-def]
    facets = json.loads(only_canonical_json(record.facets))
    update(facets)
    return OnlyMemoryProjectionRecordV1("FailureEvidenceProjectionRecord", facets, source_refs or record.source_refs)


def _semantic_query(projection: OnlyExperimentMemoryProjectionV1, *, dataset: str | None = None):
    semantic = OnlyExactSemanticHistorySelectorV1(GRAPH, NODE, "factor_value")
    if dataset is None:
        return OnlyMemoryHistoricalQueryV1(projection.revision_fingerprint, semantic)
    return OnlyMemoryHistoricalQueryV1(
        projection.revision_fingerprint,
        OnlyExactEvaluationHistorySelectorV1(
            semantic,
            CANDIDATE,
            dataset,
            SPECIFICATION,
            PLAN,
            CATALOG,
            RUNTIME,
            AUTHORING,
            (OnlyExactStatisticsReferenceV1(STATISTICS, STATISTICS_RESULT),),
            EXPERIMENT,
        ),
    )


def test_exact_semantic_and_completed_evaluation_have_deterministic_identity(tmp_path: Path) -> None:
    store, projection = _store(tmp_path)
    semantic = only_query_experiment_memory_history(store, _semantic_query(projection))
    evaluation = only_query_experiment_memory_history(store, _semantic_query(projection, dataset=DATASET))

    assert semantic.proof_status is OnlyMemoryHistoricalProofStatus.MATCH
    assert evaluation.proof_status is OnlyMemoryHistoricalProofStatus.MATCH
    assert semantic == only_query_experiment_memory_history(store, _semantic_query(projection))
    assert (
        semantic.result_fingerprint
        == only_query_experiment_memory_history(store, _semantic_query(projection)).result_fingerprint
    )


def test_semantic_match_does_not_collapse_a_different_dataset_or_failed_run(tmp_path: Path) -> None:
    store, projection = _store(tmp_path)
    assert only_query_experiment_memory_history(store, _semantic_query(projection)).proof_status is (
        OnlyMemoryHistoricalProofStatus.MATCH
    )
    assert only_query_experiment_memory_history(store, _semantic_query(projection, dataset="0" * 64)).proof_status is (
        OnlyMemoryHistoricalProofStatus.CERTIFIED_NO_MATCH
    )
    failed = replace(
        _semantic_query(projection, dataset=DATASET).exact_selector,
        specification_fingerprint="c" * 64,
        catalog_generation_fingerprint="d" * 64,
        runtime_generation_fingerprint="e" * 64,
        authoring_generation_fingerprint=None,
        search_experiment_fingerprint=None,
    )
    assert (
        only_query_experiment_memory_history(
            store, OnlyMemoryHistoricalQueryV1(projection.revision_fingerprint, failed)
        ).proof_status
        is OnlyMemoryHistoricalProofStatus.CERTIFIED_NO_MATCH
    )


def test_certified_no_match_unavailable_incomplete_and_unsupported_are_distinct(tmp_path: Path) -> None:
    store, projection = _store(tmp_path)
    absent = OnlyMemoryHistoricalQueryV1(
        projection.revision_fingerprint, OnlyExactSemanticHistorySelectorV1("0" * 64, NODE, "factor_value")
    )
    assert only_query_experiment_memory_history(store, absent).proof_status is (
        OnlyMemoryHistoricalProofStatus.CERTIFIED_NO_MATCH
    )
    missing = replace(absent, projection_revision_fingerprint="f" * 64)
    assert only_query_experiment_memory_history(store, missing).proof_status is (
        OnlyMemoryHistoricalProofStatus.PROOF_UNAVAILABLE
    )
    unsupported = replace(absent, query_schema_version=2)
    assert only_query_experiment_memory_history(store, unsupported).failure_code == "QUERY_SCHEMA_UNSUPPORTED"

    incomplete_store, incomplete_projection = _store(tmp_path / "incomplete", _projection(incomplete=True))
    incomplete = replace(absent, projection_revision_fingerprint=incomplete_projection.revision_fingerprint)
    assert only_query_experiment_memory_history(incomplete_store, incomplete).proof_status is (
        OnlyMemoryHistoricalProofStatus.PROOF_INCOMPLETE
    )


def test_corruption_is_never_certified_absence(tmp_path: Path) -> None:
    store, projection = _store(tmp_path)
    query = _semantic_query(projection)
    target = store._target(projection.revision_fingerprint) / "projection.json"
    target.write_text("{}", encoding="utf-8")
    assert only_query_experiment_memory_history(store, query).proof_status is (
        OnlyMemoryHistoricalProofStatus.PROOF_UNAVAILABLE
    )


def test_parameter_cells_and_failures_are_exact_only(tmp_path: Path) -> None:
    store, projection = _store(tmp_path)
    cell = OnlyExactParameterObservationSelectorV1.from_normalized_assignment(
        experiment_fingerprint=EXPERIMENT,
        search_space_fingerprint=SPACE,
        proposal_fingerprint=PROPOSAL,
        normalized_assignment=ASSIGNMENT,
        grid_ordinal=2,
    )
    observed = only_query_experiment_memory_history(
        store, OnlyMemoryHistoricalQueryV1(projection.revision_fingerprint, cell)
    )
    unseen = only_query_experiment_memory_history(
        store, OnlyMemoryHistoricalQueryV1(projection.revision_fingerprint, replace(cell, grid_ordinal=3))
    )
    failure = only_query_experiment_memory_history(
        store,
        OnlyMemoryHistoricalQueryV1(
            projection.revision_fingerprint,
            OnlyExactFailureEvidenceSelectorV1(
                "OPERATIONAL_FAILURE",
                "ARTIFACT_COMMIT_FAILED",
                OnlyResearchRunFailureOwnerV1(FAILED_RUN_ID, 2),
            ),
        ),
    )
    assert observed.proof_status is OnlyMemoryHistoricalProofStatus.MATCH
    assert unseen.proof_status is OnlyMemoryHistoricalProofStatus.CERTIFIED_NO_MATCH
    assert failure.proof_status is OnlyMemoryHistoricalProofStatus.MATCH
    assert failure.ordered_matches[0].to_dict()["facets"]["classification"] == "OPERATIONAL_FAILURE"
    context = failure.ordered_matches[0].to_dict()["facets"]["run_context"]
    assert context["run_id"] == FAILED_RUN_ID
    assert context["run_revision"] == 2
    assert context["search_lineage"]["experiment_fingerprint"] == EXPERIMENT


def test_evaluation_exact_distinguishes_statistics_result_identity(tmp_path: Path) -> None:
    projection = _projection()
    original = next(record for record in projection.records if record.kind == "EvaluationProjectionRecord")
    facets = json.loads(only_canonical_json(original.facets))
    facets["statistics_references"][0]["statistics_result_fingerprint"] = OTHER_STATISTICS_RESULT
    other = OnlyMemoryProjectionRecordV1("EvaluationProjectionRecord", facets, original.source_refs)
    records = tuple(sorted((*projection.records, other), key=lambda item: only_canonical_json(item.to_dict())))
    divergent = OnlyExperimentMemoryProjectionV1(projection.source_manifest, records)
    store, divergent = _store(tmp_path, divergent)

    proof = only_query_experiment_memory_history(store, _semantic_query(divergent, dataset=DATASET))

    assert proof.proof_status is OnlyMemoryHistoricalProofStatus.MATCH
    assert len(proof.ordered_matches) == 1
    assert proof.ordered_matches[0].to_dict()["facets"]["statistics_references"] == [
        {"statistics_fingerprint": STATISTICS, "statistics_result_fingerprint": STATISTICS_RESULT}
    ]


def test_missing_statistics_result_is_incomplete_even_when_another_record_matches(tmp_path: Path) -> None:
    projection = _projection()
    original = next(record for record in projection.records if record.kind == "EvaluationProjectionRecord")
    facets = json.loads(only_canonical_json(original.facets))
    del facets["statistics_references"][0]["statistics_result_fingerprint"]
    malformed = OnlyMemoryProjectionRecordV1("EvaluationProjectionRecord", facets, original.source_refs)
    records = tuple(sorted((*projection.records, malformed), key=lambda item: only_canonical_json(item.to_dict())))
    projection = OnlyExperimentMemoryProjectionV1(projection.source_manifest, records)
    store, projection = _store(tmp_path, projection)

    assert (
        only_query_experiment_memory_history(store, _semantic_query(projection, dataset=DATASET)).proof_status
        is OnlyMemoryHistoricalProofStatus.PROOF_INCOMPLETE
    )


@pytest.mark.parametrize(
    "field,value",
    (
        ("artifact_content_fingerprint", None),
        ("artifact_content_fingerprint", "not-a-sha"),
        ("calculation_execution_evidence_fingerprints", []),
        ("calculation_execution_evidence_fingerprints", ["b" * 64, "b" * 64]),
        ("calculation_execution_evidence_fingerprints", ["not-a-sha"]),
        ("calculation_execution_evidence_fingerprints", ["c" * 64, "b" * 64]),
    ),
)
def test_malformed_completed_artifact_or_execution_evidence_is_incomplete(
    tmp_path: Path, field: str, value: object
) -> None:
    def update(facets):  # type: ignore[no-untyped-def]
        facets["run_evaluation_closures"][0][field] = value

    projection = _replace_record_facets(_projection(), "EvaluationProjectionRecord", update)
    store, projection = _store(tmp_path, projection)
    assert (
        only_query_experiment_memory_history(store, _semantic_query(projection, dataset=DATASET)).proof_status
        is OnlyMemoryHistoricalProofStatus.PROOF_INCOMPLETE
    )


def test_failed_run_with_result_never_matches_evaluation_exact(tmp_path: Path) -> None:
    def update(facets):  # type: ignore[no-untyped-def]
        facets["run_evaluation_closures"] = [facets["run_evaluation_closures"][1]]

    projection = _replace_record_facets(_projection(), "EvaluationProjectionRecord", update)
    store, projection = _store(tmp_path, projection)
    assert (
        only_query_experiment_memory_history(store, _semantic_query(projection, dataset=DATASET)).proof_status
        is OnlyMemoryHistoricalProofStatus.CERTIFIED_NO_MATCH
    )


def test_run_failure_requires_complete_context_and_exact_search_lineage(tmp_path: Path) -> None:
    store, projection = _store(tmp_path)
    owner = OnlyResearchRunFailureOwnerV1(
        FAILED_RUN_ID,
        2,
        search_experiment_fingerprint=EXPERIMENT,
        search_iteration_plan_fingerprint=PROPOSAL,
    )
    query = OnlyMemoryHistoricalQueryV1(
        projection.revision_fingerprint,
        OnlyExactFailureEvidenceSelectorV1("OPERATIONAL_FAILURE", "ARTIFACT_COMMIT_FAILED", owner),
    )
    assert only_query_experiment_memory_history(store, query).proof_status is OnlyMemoryHistoricalProofStatus.MATCH
    wrong = replace(owner, search_experiment_fingerprint="0" * 64)
    assert (
        only_query_experiment_memory_history(
            store,
            replace(query, exact_selector=replace(query.exact_selector, owner=wrong)),
        ).proof_status
        is OnlyMemoryHistoricalProofStatus.CERTIFIED_NO_MATCH
    )

    def update(facets):  # type: ignore[no-untyped-def]
        del facets["run_context"]["runtime_generation_fingerprint"]

    malformed = _replace_record_facets(projection, "FailureEvidenceProjectionRecord", update)
    malformed_store, malformed = _store(tmp_path / "malformed", malformed)
    malformed_query = replace(query, projection_revision_fingerprint=malformed.revision_fingerprint)
    assert (
        only_query_experiment_memory_history(malformed_store, malformed_query).proof_status
        is OnlyMemoryHistoricalProofStatus.PROOF_INCOMPLETE
    )


def test_failed_and_cancelled_run_terminals_are_exact_and_do_not_poison_each_other(tmp_path: Path) -> None:
    base = _projection()
    failed = _run_terminal_record(base)
    cancelled_id = "00000000-0000-4000-8000-000000000005"
    cancelled = _run_terminal_record(base, run_id=cancelled_id, revision=1, state="CANCELLED")
    projection = _with_failure_records(base, failed, cancelled)
    failed_selector = OnlyExactFailureEvidenceSelectorV1(
        "OPERATIONAL_FAILURE",
        "RESEARCH_EXECUTION_FAILED",
        OnlyResearchRunTerminalOwnerV1(FAILED_RUN_ID, 2, terminal_state="FAILED"),
        "EXECUTION",
    )
    cancelled_selector = OnlyExactFailureEvidenceSelectorV1(
        "OPERATIONAL_FAILURE",
        None,
        OnlyResearchRunTerminalOwnerV1(cancelled_id, 1, terminal_state="CANCELLED"),
    )

    assert _failure_status(tmp_path / "failed", projection, failed_selector) is OnlyMemoryHistoricalProofStatus.MATCH
    assert _failure_status(tmp_path / "cancelled", projection, cancelled_selector) is (
        OnlyMemoryHistoricalProofStatus.MATCH
    )
    assert (
        _failure_status(tmp_path / "wrong_code", projection, replace(failed_selector, stable_code="OTHER_FAILURE"))
        is OnlyMemoryHistoricalProofStatus.CERTIFIED_NO_MATCH
    )
    assert (
        _failure_status(
            tmp_path / "different",
            projection,
            replace(cancelled_selector, owner=replace(cancelled_selector.owner, run_revision=2)),
        )
        is OnlyMemoryHistoricalProofStatus.CERTIFIED_NO_MATCH
    )

    fabricated = _mutate_failure_record(
        cancelled,
        lambda facets: facets.update(
            failure_phase="EXECUTION", failure_code="FAKE_CANCELLATION", failure_detail="fabricated"
        ),
    )
    assert (
        _failure_status(tmp_path / "fabricated", _with_failure_records(base, fabricated), cancelled_selector)
        is OnlyMemoryHistoricalProofStatus.PROOF_INCOMPLETE
    )


def test_run_terminal_structural_loss_is_always_incomplete(tmp_path: Path) -> None:
    base = _projection()
    record = _run_terminal_record(base)
    selector = OnlyExactFailureEvidenceSelectorV1(
        "OPERATIONAL_FAILURE",
        "RESEARCH_EXECUTION_FAILED",
        OnlyResearchRunTerminalOwnerV1(FAILED_RUN_ID, 2, terminal_state="FAILED"),
    )
    unrelated = _source_ref(base, "PRODUCT_COMMAND_RECEIPT", "f" * 64)
    duplicate = _source_ref(base, "RESEARCH_RUN", "e" * 64)
    mutations = {
        "owner_context": _mutate_failure_record(record, lambda facets: facets.pop("run_context")),
        "owner_identity": _mutate_failure_record(record, lambda facets: facets["run_context"].pop("run_id")),
        "nested_relation": _mutate_failure_record(record, lambda facets: facets["run_context"].pop("search_lineage")),
        "source_ref": _mutate_failure_record(record, lambda _: None, source_refs=(unrelated,)),
        "leaf_fingerprint": _mutate_failure_record(
            record,
            lambda facets: facets["run_context"].update(specification_fingerprint="not-a-sha"),
        ),
        "duplicate_owner_ref": _mutate_failure_record(
            record, lambda _: None, source_refs=(*record.source_refs, duplicate)
        ),
        "missing_code": _mutate_failure_record(record, lambda facets: facets.update(failure_code=None)),
        "missing_phase": _mutate_failure_record(record, lambda facets: facets.update(failure_phase=None)),
    }
    for name, malformed in mutations.items():
        assert (
            _failure_status(tmp_path / name, _with_failure_records(base, malformed), selector)
            is OnlyMemoryHistoricalProofStatus.PROOF_INCOMPLETE
        )
    different = _run_terminal_record(base, run_id="00000000-0000-4000-8000-000000000006", revision=2)
    assert (
        _failure_status(tmp_path / "different_identity", _with_failure_records(base, different), selector)
        is OnlyMemoryHistoricalProofStatus.CERTIFIED_NO_MATCH
    )


def test_failure_selector_rejects_semantically_impossible_terminal_payloads() -> None:
    cancelled = OnlyResearchRunTerminalOwnerV1(FAILED_RUN_ID, 2, terminal_state="CANCELLED")
    with pytest.raises(ValueError, match="CANCELLED"):
        OnlyExactFailureEvidenceSelectorV1("OPERATIONAL_FAILURE", "FAKE_CANCELLATION", cancelled)
    with pytest.raises(ValueError, match="classification is incompatible"):
        OnlyExactFailureEvidenceSelectorV1(
            "QUALIFICATION_REJECT", "OTHER_REJECTION", OnlyQualificationFailureOwnerV1("b" * 64)
        )


def test_failure_owner_is_native_typed_occurrence_not_any_source_ref(tmp_path: Path) -> None:
    projection = _projection()
    search_identity = "7" * 64
    search_ref = OnlyMemorySourceRefV1(
        "SEARCH_PROVENANCE",
        projection.source_manifest.cuts[-1].cut_fingerprint,
        f"iteration-results/{search_identity}",
        search_identity,
        search_identity,
    )
    search_failure = OnlyMemoryProjectionRecordV1(
        "FailureEvidenceProjectionRecord",
        {
            "classification": "SEARCH_OR_BUDGET_STOP",
            "failure_code": "SEARCH_BUDGET_EXHAUSTED",
            "iteration_result_fingerprint": search_identity,
        },
        (search_ref,),
    )
    records = tuple(sorted((*projection.records, search_failure), key=lambda item: only_canonical_json(item.to_dict())))
    projection = OnlyExperimentMemoryProjectionV1(projection.source_manifest, records)
    store, projection = _store(tmp_path, projection)

    exact = OnlyMemoryHistoricalQueryV1(
        projection.revision_fingerprint,
        OnlyExactFailureEvidenceSelectorV1(
            "SEARCH_OR_BUDGET_STOP", "SEARCH_BUDGET_EXHAUSTED", OnlySearchFailureOwnerV1(search_identity)
        ),
    )
    provenance = replace(
        exact,
        exact_selector=replace(exact.exact_selector, owner=OnlySearchFailureOwnerV1(EXPERIMENT)),
    )
    assert only_query_experiment_memory_history(store, exact).proof_status is OnlyMemoryHistoricalProofStatus.MATCH
    assert (
        only_query_experiment_memory_history(store, provenance).proof_status
        is OnlyMemoryHistoricalProofStatus.CERTIFIED_NO_MATCH
    )
    provenance_only = OnlyMemoryHistoricalQueryV1(
        projection.revision_fingerprint,
        OnlyExactFailureEvidenceSelectorV1(
            "OPERATIONAL_FAILURE", "ARTIFACT_COMMIT_FAILED", OnlySearchFailureOwnerV1(EXPERIMENT)
        ),
    )
    assert (
        only_query_experiment_memory_history(store, provenance_only).proof_status
        is OnlyMemoryHistoricalProofStatus.CERTIFIED_NO_MATCH
    )


def test_qualification_reject_never_matches_operational_failure(tmp_path: Path) -> None:
    projection = _projection()
    decision = "a" * 64
    cut = next(cut for cut in projection.source_manifest.cuts if cut.source_family == "QUALIFICATION_DECISION")
    qualification_ref = OnlyMemorySourceRefV1(
        "QUALIFICATION_DECISION", cut.cut_fingerprint, decision, decision, decision
    )
    qualification = OnlyMemoryProjectionRecordV1(
        "FailureEvidenceProjectionRecord",
        {
            "classification": "QUALIFICATION_REJECT",
            "subject_strategy_fingerprint": "b" * 64,
            "policy_id": "policy",
            "policy_version": "1",
            "policy_fingerprint": "c" * 64,
            "evidence_refs": [
                {
                    "kind": "BACKTEST_EVIDENCE",
                    "evidence_fingerprint": "d" * 64,
                    "locator_fingerprint": None,
                    "subject_binding_fingerprint": None,
                }
            ],
        },
        (qualification_ref,),
    )
    records = tuple(sorted((*projection.records, qualification), key=lambda item: only_canonical_json(item.to_dict())))
    projection = OnlyExperimentMemoryProjectionV1(projection.source_manifest, records)
    store, projection = _store(tmp_path, projection)
    exact = OnlyMemoryHistoricalQueryV1(
        projection.revision_fingerprint,
        OnlyExactFailureEvidenceSelectorV1(
            "QUALIFICATION_REJECT", "QUALIFICATION_REJECTED", OnlyQualificationFailureOwnerV1(decision)
        ),
    )
    operational = OnlyMemoryHistoricalQueryV1(
        projection.revision_fingerprint,
        OnlyExactFailureEvidenceSelectorV1(
            "OPERATIONAL_FAILURE", "QUALIFICATION_REJECTED", OnlySearchFailureOwnerV1(decision)
        ),
    )
    assert only_query_experiment_memory_history(store, exact).proof_status is OnlyMemoryHistoricalProofStatus.MATCH
    assert (
        only_query_experiment_memory_history(store, operational).proof_status
        is OnlyMemoryHistoricalProofStatus.CERTIFIED_NO_MATCH
    )


@pytest.mark.parametrize("family", ("SEARCH", "AGENT", "QUALIFICATION"))
def test_typed_owner_structural_mutations_are_incomplete_and_different_identity_is_not(
    tmp_path: Path, family: str
) -> None:
    base = _projection()
    if family == "SEARCH":
        record = _search_failure_record(base)
        selector = OnlyExactFailureEvidenceSelectorV1(
            "SEARCH_OR_BUDGET_STOP", "SEARCH_BUDGET_EXHAUSTED", OnlySearchFailureOwnerV1("7" * 64)
        )
        owner_family = "SEARCH_PROVENANCE"
        identity_field = "iteration_result_fingerprint"
        nested_field = identity_field
        leaf_field = identity_field
    elif family == "AGENT":
        record = _agent_failure_record(base)
        selector = OnlyExactFailureEvidenceSelectorV1(
            "OPERATIONAL_FAILURE", "AGENT_MODEL_CALL_FAILED", OnlyAgentFailureOwnerV1("8" * 64)
        )
        owner_family = "AGENT_PROVENANCE"
        identity_field = "outcome"
        nested_field = "outcome"
        leaf_field = "failure_code"
    else:
        record = _qualification_failure_record(base)
        selector = OnlyExactFailureEvidenceSelectorV1(
            "QUALIFICATION_REJECT", "QUALIFICATION_REJECTED", OnlyQualificationFailureOwnerV1("b" * 64)
        )
        owner_family = "QUALIFICATION_DECISION"
        identity_field = "subject_strategy_fingerprint"
        nested_field = "evidence_refs"
        leaf_field = "policy_fingerprint"

    owner_ref = next(ref for ref in record.source_refs if ref.source_family == owner_family)
    malformed_ref = replace(owner_ref, locator="malformed")
    duplicate_ref = replace(owner_ref, content_fingerprint="f" * 64)
    mutations = {
        "owner_context": _mutate_failure_record(record, lambda facets: facets.pop(identity_field)),
        "owner_identity": _mutate_failure_record(
            record,
            lambda facets: facets.update(**{identity_field: None if family != "SEARCH" else "not-a-sha"}),
        ),
        "nested_relation": _mutate_failure_record(record, lambda facets: facets.pop(nested_field)),
        "source_ref": _mutate_failure_record(record, lambda _: None, source_refs=(malformed_ref,)),
        "leaf_fingerprint": _mutate_failure_record(
            record, lambda facets: facets.update(**{leaf_field: "not-a-sha" if family != "AGENT" else ""})
        ),
        "duplicate_owner_ref": _mutate_failure_record(
            record, lambda _: None, source_refs=(*record.source_refs, duplicate_ref)
        ),
    }
    for name, malformed in mutations.items():
        assert (
            _failure_status(tmp_path / name, _with_failure_records(base, malformed), selector)
            is OnlyMemoryHistoricalProofStatus.PROOF_INCOMPLETE
        )
    if family == "AGENT":
        contradictory = _mutate_failure_record(record, lambda facets: facets.update(outcome="OUTCOME_UNKNOWN"))
        assert (
            _failure_status(tmp_path / "wrong_outcome", _with_failure_records(base, contradictory), selector)
            is OnlyMemoryHistoricalProofStatus.PROOF_INCOMPLETE
        )

    different_owner = (
        replace(selector.owner, iteration_result_fingerprint="0" * 64)
        if family == "SEARCH"
        else replace(selector.owner, occurrence_fingerprint="0" * 64)
        if family == "AGENT"
        else replace(selector.owner, decision_fingerprint="0" * 64)
    )
    assert (
        _failure_status(
            tmp_path / "different",
            _with_failure_records(base, record),
            replace(selector, owner=different_owner),
        )
        is OnlyMemoryHistoricalProofStatus.CERTIFIED_NO_MATCH
    )
    assert (
        _failure_status(
            tmp_path / "wrong_code",
            _with_failure_records(base, record),
            replace(selector, stable_code="OTHER_FAILURE")
            if family != "QUALIFICATION"
            else OnlyExactFailureEvidenceSelectorV1(
                "QUALIFICATION_REJECT", "QUALIFICATION_REJECTED", OnlyQualificationFailureOwnerV1("0" * 64)
            ),
        )
        is OnlyMemoryHistoricalProofStatus.CERTIFIED_NO_MATCH
    )


def test_cross_family_records_are_isolated_and_provenance_noise_does_not_transfer_owner(tmp_path: Path) -> None:
    base = _projection()
    run = _run_terminal_record(base)
    search = _search_failure_record(base)
    agent = _agent_failure_record(base)
    qualification = _qualification_failure_record(base)
    run_noise = _source_ref(base, "RESEARCH_RUN", "1" * 64)
    search = _mutate_failure_record(search, lambda _: None, source_refs=(*search.source_refs, run_noise))
    search_noise = _source_ref(base, "SEARCH_PROVENANCE", "2" * 64, locator="experiments/" + "2" * 64)
    run = _mutate_failure_record(run, lambda _: None, source_refs=(*run.source_refs, search_noise))
    projection = _with_failure_records(base, run, search, agent, qualification)
    selectors = (
        OnlyExactFailureEvidenceSelectorV1(
            "OPERATIONAL_FAILURE",
            "RESEARCH_EXECUTION_FAILED",
            OnlyResearchRunTerminalOwnerV1(FAILED_RUN_ID, 2),
        ),
        OnlyExactFailureEvidenceSelectorV1(
            "SEARCH_OR_BUDGET_STOP", "SEARCH_BUDGET_EXHAUSTED", OnlySearchFailureOwnerV1("7" * 64)
        ),
        OnlyExactFailureEvidenceSelectorV1(
            "OPERATIONAL_FAILURE", "AGENT_MODEL_CALL_FAILED", OnlyAgentFailureOwnerV1("8" * 64)
        ),
        OnlyExactFailureEvidenceSelectorV1(
            "QUALIFICATION_REJECT", "QUALIFICATION_REJECTED", OnlyQualificationFailureOwnerV1("b" * 64)
        ),
    )
    for index, selector in enumerate(selectors):
        assert _failure_status(tmp_path / str(index), projection, selector) is OnlyMemoryHistoricalProofStatus.MATCH


def test_incomplete_relevant_owner_keeps_precedence_over_a_match(tmp_path: Path) -> None:
    base = _projection()
    complete = _search_failure_record(base)
    incomplete = _mutate_failure_record(complete, lambda facets: facets.pop("iteration_result_fingerprint"))
    selector = OnlyExactFailureEvidenceSelectorV1(
        "SEARCH_OR_BUDGET_STOP", "SEARCH_BUDGET_EXHAUSTED", OnlySearchFailureOwnerV1("7" * 64)
    )
    assert (
        _failure_status(tmp_path, _with_failure_records(base, complete, incomplete), selector)
        is OnlyMemoryHistoricalProofStatus.PROOF_INCOMPLETE
    )


def test_query_fingerprint_binds_every_new_exact_identity() -> None:
    projection = _projection()
    evaluation = _semantic_query(projection, dataset=DATASET)
    statistics_result = replace(
        evaluation,
        exact_selector=replace(
            evaluation.exact_selector,
            statistics_references=(OnlyExactStatisticsReferenceV1(STATISTICS, OTHER_STATISTICS_RESULT),),
        ),
    )
    base_owner = OnlyResearchRunFailureOwnerV1(FAILED_RUN_ID, 2, search_experiment_fingerprint=EXPERIMENT)
    failure = OnlyMemoryHistoricalQueryV1(
        projection.revision_fingerprint,
        OnlyExactFailureEvidenceSelectorV1("OPERATIONAL_FAILURE", "ARTIFACT_COMMIT_FAILED", base_owner),
    )
    variants = (
        replace(failure, exact_selector=replace(failure.exact_selector, stable_code="OTHER_FAILURE")),
        replace(failure, exact_selector=replace(failure.exact_selector, failure_phase="EXECUTION")),
        replace(failure, exact_selector=replace(failure.exact_selector, owner=replace(base_owner, run_revision=3))),
        replace(
            failure,
            exact_selector=replace(
                failure.exact_selector,
                owner=replace(base_owner, run_id="00000000-0000-4000-8000-000000000004"),
            ),
        ),
        replace(
            failure,
            exact_selector=replace(
                failure.exact_selector, owner=replace(base_owner, search_experiment_fingerprint="0" * 64)
            ),
        ),
    )
    cancellation = OnlyMemoryHistoricalQueryV1(
        projection.revision_fingerprint,
        OnlyExactFailureEvidenceSelectorV1(
            "OPERATIONAL_FAILURE",
            None,
            replace(base_owner, terminal_state="CANCELLED"),
        ),
    )
    owner_queries = (
        OnlyMemoryHistoricalQueryV1(
            projection.revision_fingerprint,
            OnlyExactFailureEvidenceSelectorV1(
                "SEARCH_OR_BUDGET_STOP", "SEARCH_BUDGET_EXHAUSTED", OnlySearchFailureOwnerV1("7" * 64)
            ),
        ),
        OnlyMemoryHistoricalQueryV1(
            projection.revision_fingerprint,
            OnlyExactFailureEvidenceSelectorV1(
                "OPERATIONAL_FAILURE", "AGENT_MODEL_CALL_FAILED", OnlyAgentFailureOwnerV1("8" * 64)
            ),
        ),
        OnlyMemoryHistoricalQueryV1(
            projection.revision_fingerprint,
            OnlyExactFailureEvidenceSelectorV1(
                "QUALIFICATION_REJECT", "QUALIFICATION_REJECTED", OnlyQualificationFailureOwnerV1("b" * 64)
            ),
        ),
    )
    assert evaluation.query_fingerprint != statistics_result.query_fingerprint
    fingerprints = {
        failure.query_fingerprint,
        cancellation.query_fingerprint,
        *(query.query_fingerprint for query in variants),
        *(query.query_fingerprint for query in owner_queries),
    }
    assert len(fingerprints) == 10
    assert failure.query_fingerprint == replace(failure).query_fingerprint


def test_old_revision_is_independent_of_active_pointer_source_growth_and_duplicate_replay(tmp_path: Path) -> None:
    store, projection = _store(tmp_path, _projection(include_evaluation=False))
    query = OnlyMemoryHistoricalQueryV1(
        projection.revision_fingerprint, OnlyExactSemanticHistorySelectorV1(GRAPH, NODE, "factor_value")
    )
    before = only_query_experiment_memory_history(store, query)
    assert before.proof_status is OnlyMemoryHistoricalProofStatus.CERTIFIED_NO_MATCH

    grown = _projection()
    store._publish_and_activate(grown)
    assert only_query_experiment_memory_history(store, query) == before
    grown_query = replace(query, projection_revision_fingerprint=grown.revision_fingerprint)
    assert (
        only_query_experiment_memory_history(store, grown_query).proof_status is OnlyMemoryHistoricalProofStatus.MATCH
    )

    duplicate = _projection(duplicate=True)
    store._publish_and_activate(duplicate)
    duplicate_query = replace(query, projection_revision_fingerprint=duplicate.revision_fingerprint)
    duplicate_result = only_query_experiment_memory_history(store, duplicate_query)
    assert len(duplicate_result.ordered_matches) == 1


def test_fresh_rebuild_reproduces_query_and_result_identity(tmp_path: Path) -> None:
    store, projection = _store(tmp_path)
    queries = (
        _semantic_query(projection),
        _semantic_query(projection, dataset=DATASET),
        OnlyMemoryHistoricalQueryV1(
            projection.revision_fingerprint,
            OnlyExactFailureEvidenceSelectorV1(
                "OPERATIONAL_FAILURE",
                "ARTIFACT_COMMIT_FAILED",
                OnlyResearchRunFailureOwnerV1(FAILED_RUN_ID, 2),
            ),
        ),
    )
    before = tuple(only_query_experiment_memory_history(store, query) for query in queries)
    shutil.rmtree(tmp_path / "experiment-memory")
    rebuilt_store, rebuilt = _store(tmp_path, projection)
    after = tuple(only_query_experiment_memory_history(rebuilt_store, query) for query in queries)
    assert rebuilt.revision_fingerprint == projection.revision_fingerprint
    assert rebuilt.logical_digest == projection.logical_digest
    assert after == before
    assert tuple(proof.result_fingerprint for proof in after) == tuple(proof.result_fingerprint for proof in before)
