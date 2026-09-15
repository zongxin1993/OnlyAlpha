"""Exact history query identity, proof-state and revision-isolation tests."""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.memory.projector import (
    OnlyExperimentMemoryProjectionV1,
    OnlyMemoryProjectionRecordV1,
    OnlyMemorySourceRefV1,
)
from onlyalpha.research.memory.query import (
    OnlyExactEvaluationHistorySelectorV1,
    OnlyExactFailureEvidenceSelectorV1,
    OnlyExactParameterObservationSelectorV1,
    OnlyExactSemanticHistorySelectorV1,
    OnlyMemoryHistoricalProofStatus,
    OnlyMemoryHistoricalQueryV1,
    only_query_experiment_memory_history,
)
from onlyalpha.research.memory.source_manifest import MANDATORY_FAMILIES, OnlyExperimentMemorySourceCutManifestV1
from onlyalpha.research.memory.store import OnlyExperimentMemoryRevisionStore
from onlyalpha.research.source_cut import OnlySourceClosedCutV1

GRAPH, NODE, CANDIDATE = "a" * 64, "b" * 64, "c" * 64
DATASET, SPECIFICATION, PLAN, RESULT = "d" * 64, "e" * 64, "f" * 64, "1" * 64
CATALOG, RUNTIME, AUTHORING, STATISTICS = "2" * 64, "3" * 64, "4" * 64, "5" * 64
EXPERIMENT, SPACE, PROPOSAL, FAILURE = "6" * 64, "7" * 64, "8" * 64, "9" * 64
ASSIGNMENT = [{"target": "window", "value": 20}]


def _projection(
    *, duplicate: bool = False, incomplete: bool = False, include_evaluation: bool = True
) -> OnlyExperimentMemoryProjectionV1:
    cuts = {family: OnlySourceClosedCutV1(family, 1, ()) for family in MANDATORY_FAMILIES}
    manifest = OnlyExperimentMemorySourceCutManifestV1.from_cuts(tuple(cuts.values()))

    def ref(family: str, identity: str) -> OnlyMemorySourceRefV1:
        return OnlyMemorySourceRefV1(family, cuts[family].cut_fingerprint, identity, identity, identity)

    semantic = {
        "candidate_fingerprint": CANDIDATE,
        "graph_fingerprint": GRAPH,
        "candidate_node_fingerprint": NODE,
        "output_name": "factor_value",
        "dataset_snapshot_fingerprint": DATASET,
        "research_result_locator": PLAN,
        "research_result_fingerprint": RESULT,
        "statistics_references": [{"statistics_fingerprint": STATISTICS, "statistics_result_fingerprint": "0" * 64}],
        "run_evaluation_closures": [
            {
                "run_id": "00000000-0000-4000-8000-000000000001",
                "run_revision": 2,
                "run_state": "COMPLETED",
                "specification_fingerprint": SPECIFICATION,
                "research_result_fingerprint": RESULT,
                "artifact_content_fingerprint": "a" * 64,
                "catalog_generation_fingerprint": CATALOG,
                "runtime_generation_fingerprint": RUNTIME,
                "authoring_generation_fingerprint": AUTHORING,
                "calculation_execution_evidence_fingerprints": ["b" * 64],
                "search_lineage": {"experiment_fingerprint": EXPERIMENT},
            },
            {
                "run_id": "00000000-0000-4000-8000-000000000002",
                "run_revision": 2,
                "run_state": "FAILED",
                "specification_fingerprint": "c" * 64,
                "research_result_fingerprint": RESULT,
                "artifact_content_fingerprint": None,
                "catalog_generation_fingerprint": "d" * 64,
                "runtime_generation_fingerprint": "e" * 64,
                "authoring_generation_fingerprint": None,
                "calculation_execution_evidence_fingerprints": [],
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
                "run_id": "00000000-0000-4000-8000-000000000002",
                "run_state": "FAILED",
                "research_result_fingerprint": RESULT,
                "artifact_content_fingerprint": None,
            },
        },
        (ref("RESEARCH_RUN", FAILURE),),
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
            (STATISTICS,),
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
            OnlyExactFailureEvidenceSelectorV1("OPERATIONAL_FAILURE", "ARTIFACT_COMMIT_FAILED", FAILURE),
        ),
    )
    assert observed.proof_status is OnlyMemoryHistoricalProofStatus.MATCH
    assert unseen.proof_status is OnlyMemoryHistoricalProofStatus.CERTIFIED_NO_MATCH
    assert failure.proof_status is OnlyMemoryHistoricalProofStatus.MATCH
    assert failure.ordered_matches[0].to_dict()["facets"]["classification"] == "OPERATIONAL_FAILURE"
    assert failure.ordered_matches[0].to_dict()["facets"]["run_context"] == {
        "run_id": "00000000-0000-4000-8000-000000000002",
        "run_state": "FAILED",
        "research_result_fingerprint": RESULT,
        "artifact_content_fingerprint": None,
    }


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
    query = _semantic_query(projection)
    before = only_query_experiment_memory_history(store, query)
    shutil.rmtree(tmp_path / "experiment-memory")
    rebuilt_store, rebuilt = _store(tmp_path, projection)
    after = only_query_experiment_memory_history(rebuilt_store, query)
    assert rebuilt.revision_fingerprint == projection.revision_fingerprint
    assert rebuilt.logical_digest == projection.logical_digest
    assert after == before
    assert after.result_fingerprint == before.result_fingerprint
