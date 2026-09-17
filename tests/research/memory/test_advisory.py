from __future__ import annotations

import json
import shutil
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.research.evaluation.subject import OnlyExactEvaluationIntentSubjectV1
from onlyalpha.research.memory.advisory import (
    OnlyExperimentMemoryAdvisoryProjectionBuilder,
    OnlyNearDuplicateAdvisoryContextTier,
    OnlyNearDuplicateMatchV1,
    OnlyNearDuplicateQueryV1,
    OnlyNearDuplicateResultStatus,
    OnlyNearDuplicateResultV1,
    OnlyNearDuplicateThresholdPolicyV1,
    OnlyResearchAdvisoryIndexV1,
    OnlyResearchAdvisoryRepresentationV1,
    OnlyResearchAdvisorySourceRefV1,
    OnlyResearchAdvisoryUnavailableError,
    only_build_research_advisory_index,
    only_build_research_advisory_representation,
    only_query_near_duplicates,
)
from onlyalpha.research.memory.projector import (
    OnlyExperimentMemoryProjectionV1,
    OnlyMemoryProjectionRecordV1,
    OnlyMemorySourceRefV1,
)
from onlyalpha.research.memory.source_manifest import MANDATORY_FAMILIES, OnlyExperimentMemorySourceCutManifestV1
from onlyalpha.research.memory.store import OnlyExperimentMemoryRevisionStore
from onlyalpha.research.source_cut import OnlySourceClosedCutV1, OnlySourceCutEntryV1, OnlySourceObservationV1
from tests.research.factor.support import factor_graph
from tests.research.specification.support import scientific_specification

PROJECTION = "1" * 64
CUT = "2" * 64


def _representation(
    identity: str,
    *,
    direction: str = "HIGHER_IS_BETTER",
    dataset: str = "a" * 64,
    projection: str = PROJECTION,
    runtime: str = "6" * 64,
):
    graph = factor_graph(direction)
    specification = scientific_specification(dataset)
    node = next(item for item in graph.ordered_nodes if item.definition.type_id == "example.factor.momentum")
    subject = OnlyExactEvaluationIntentSubjectV1(
        graph.fingerprint,
        node.fingerprint,
        "factor_value",
        identity,
        dataset,
        specification.specification_fingerprint,
        "3" * 64,
        ("4" * 64,),
        "5" * 64,
        runtime,
        None,
    )
    return only_build_research_advisory_representation(
        subject=subject,
        graph=graph,
        specification=specification,
        source_ref=OnlyResearchAdvisorySourceRefV1("RESEARCH_RESULT", f"results/{identity}", identity, identity),
        projection_revision=projection,
        source_cut_fingerprint=CUT,
    )


class _Verifier:
    def __init__(self, *representations, unavailable: bool = False):  # type: ignore[no-untyped-def]
        self.values = {item.source_ref: item for item in representations}
        self.unavailable = unavailable

    def load_representation_verified(self, source_ref, projection_revision, representation_schema_version):  # type: ignore[no-untyped-def]
        if self.unavailable:
            raise OnlyResearchAdvisoryUnavailableError("source down")
        value = self.values[source_ref]
        assert value.projection_revision == projection_revision
        assert value.representation_schema_version == representation_schema_version
        return value


def _policy() -> OnlyNearDuplicateThresholdPolicyV1:
    return OnlyNearDuplicateThresholdPolicyV1("structured-default", "1", Decimal("0.5"), Decimal("0.8"), 10)


def _query(current, index, policy=None):  # type: ignore[no-untyped-def]
    policy = policy or _policy()
    return OnlyNearDuplicateQueryV1(
        current.representation_fingerprint,
        current.projection_revision,
        current.source_cut_fingerprint,
        index.index_build_revision,
        policy.policy_fingerprint,
        10,
    )


def test_representation_is_versioned_canonical_and_uses_semantic_features() -> None:
    representation = _representation("7" * 64)
    loaded = type(representation).from_dict(representation.to_dict())

    assert loaded == representation
    assert loaded.representation_schema_version == 1
    assert any("example.factor.momentum" in value for value in loaded.operator_features)
    assert not hasattr(loaded, "graph_fingerprint")
    assert all(feature.key.count("|") >= 3 for feature in loaded.parameter_features)


def test_structured_retrieval_is_deterministic_comparable_and_rebuildable() -> None:
    current = _representation("8" * 64)
    near = _representation("9" * 64, direction="LOWER_IS_BETTER")
    same_score_later = replace(
        near,
        source_ref=OnlyResearchAdvisorySourceRefV1("RESEARCH_RESULT", "results/z", "z", "a" * 64),
    )
    first_index = only_build_research_advisory_index(PROJECTION, CUT, (same_score_later, near))
    rebuilt = only_build_research_advisory_index(PROJECTION, CUT, (near, same_score_later))
    verifier = _Verifier(near, same_score_later)

    first = only_query_near_duplicates(
        current=current,
        query=_query(current, first_index),
        index=first_index,
        policy=_policy(),
        source_verifier=verifier,
    )
    second = only_query_near_duplicates(
        current=current,
        query=_query(current, rebuilt),
        index=rebuilt,
        policy=_policy(),
        source_verifier=verifier,
    )

    assert first == second
    assert first_index.index_build_revision == rebuilt.index_build_revision
    assert first.status is OnlyNearDuplicateResultStatus.ADVISORY_OK
    assert tuple(match.native_locator for match in first.matches) == (near.source_ref.native_locator, "results/z")
    assert OnlyNearDuplicateAdvisoryContextTier.COMPARABLE in first.matches[0].context_tiers
    assert OnlyNearDuplicateAdvisoryContextTier.ADVISORY_SIMILAR in first.matches[0].context_tiers
    assert "PARAMETERS" in first.matches[0].different
    assert {tier.value for tier in OnlyNearDuplicateAdvisoryContextTier} == {
        "RETRIEVABLE",
        "COMPARABLE",
        "ADVISORY_SIMILAR",
    }


def test_different_dataset_can_be_similar_but_is_not_comparable() -> None:
    current = _representation("8" * 64)
    historical = _representation("9" * 64, dataset="b" * 64)
    index = only_build_research_advisory_index(PROJECTION, CUT, (historical,))
    result = only_query_near_duplicates(
        current=current,
        query=_query(current, index),
        index=index,
        policy=_policy(),
        source_verifier=_Verifier(historical),
    )

    assert result.status is OnlyNearDuplicateResultStatus.ADVISORY_OK
    assert result.matches
    assert OnlyNearDuplicateAdvisoryContextTier.RETRIEVABLE in result.matches[0].context_tiers
    assert OnlyNearDuplicateAdvisoryContextTier.ADVISORY_SIMILAR in result.matches[0].context_tiers
    assert OnlyNearDuplicateAdvisoryContextTier.COMPARABLE not in result.matches[0].context_tiers
    assert "DATASET" in result.matches[0].different


def test_different_runtime_generation_is_not_silently_comparable() -> None:
    current = _representation("8" * 64)
    historical = _representation("9" * 64, runtime="e" * 64)
    index = only_build_research_advisory_index(PROJECTION, CUT, (historical,))
    result = only_query_near_duplicates(
        current=current,
        query=_query(current, index),
        index=index,
        policy=_policy(),
        source_verifier=_Verifier(historical),
    )

    assert result.matches
    assert OnlyNearDuplicateAdvisoryContextTier.COMPARABLE not in result.matches[0].context_tiers
    assert "EVALUATION_CONTEXT" in result.matches[0].different


def test_orphan_is_partial_and_backend_failure_is_not_an_empty_success() -> None:
    current = _representation("8" * 64)
    orphan = _representation("9" * 64)
    index = only_build_research_advisory_index(PROJECTION, CUT, (orphan,))
    query = _query(current, index)

    partial = only_query_near_duplicates(
        current=current,
        query=query,
        index=index,
        policy=_policy(),
        source_verifier=_Verifier(),
    )
    unavailable = only_query_near_duplicates(
        current=current,
        query=query,
        index=index,
        policy=_policy(),
        source_verifier=_Verifier(unavailable=True),
    )
    missing_index = only_query_near_duplicates(
        current=current,
        query=query,
        index=None,
        policy=_policy(),
        source_verifier=_Verifier(),
    )

    assert (partial.status, partial.matches, partial.failure_code) == (
        OnlyNearDuplicateResultStatus.ADVISORY_PARTIAL,
        (),
        "SOURCE_VERIFICATION_REJECTED",
    )
    assert unavailable.status is OnlyNearDuplicateResultStatus.ADVISORY_UNAVAILABLE
    assert missing_index.status is OnlyNearDuplicateResultStatus.ADVISORY_UNAVAILABLE
    assert missing_index.source_cut_fingerprint == query.source_cut_fingerprint


def test_projection_policy_and_model_identity_cannot_be_silently_mixed() -> None:
    current = _representation("8" * 64)
    historical = _representation("9" * 64)
    index = only_build_research_advisory_index(PROJECTION, CUT, (historical,))
    query = replace(_query(current, index), projection_revision="f" * 64)
    result = only_query_near_duplicates(
        current=current,
        query=query,
        index=index,
        policy=_policy(),
        source_verifier=_Verifier(historical),
    )

    assert result.status is OnlyNearDuplicateResultStatus.ADVISORY_UNSUPPORTED
    assert result.failure_code == "QUERY_BINDING_UNSUPPORTED"
    with pytest.raises(ValueError, match="does not accept model identity"):
        replace(result, model_id="vendor/model")


def test_source_cut_and_duplicate_source_representation_conflicts_are_rejected() -> None:
    current = _representation("8" * 64)
    historical = _representation("9" * 64)
    index = only_build_research_advisory_index(PROJECTION, CUT, (historical,))
    mismatched = replace(_query(current, index), source_cut_fingerprint="d" * 64)
    result = only_query_near_duplicates(
        current=current,
        query=mismatched,
        index=index,
        policy=_policy(),
        source_verifier=_Verifier(historical),
    )
    conflict = replace(historical, evaluation_context_fingerprint="c" * 64)

    assert result.status is OnlyNearDuplicateResultStatus.ADVISORY_UNSUPPORTED
    current_from_other_cut = replace(current, source_cut_fingerprint="d" * 64)
    cross_cut = only_query_near_duplicates(
        current=current_from_other_cut,
        query=_query(current_from_other_cut, index),
        index=index,
        policy=_policy(),
        source_verifier=_Verifier(historical),
    )
    assert cross_cut.status is OnlyNearDuplicateResultStatus.ADVISORY_UNSUPPORTED
    with pytest.raises(ValueError, match="conflicting representations"):
        only_build_research_advisory_index(PROJECTION, CUT, (historical, conflict))


def test_high_similarity_remains_advisory_and_cannot_seal_an_action() -> None:
    current = _representation("8" * 64)
    historical = _representation("9" * 64)
    index = only_build_research_advisory_index(PROJECTION, CUT, (historical,))
    result = only_query_near_duplicates(
        current=current,
        query=_query(current, index),
        index=index,
        policy=_policy(),
        source_verifier=_Verifier(historical),
    )

    assert result.matches[0].score == Decimal("1.000000000000")
    assert not hasattr(result, "outcome")
    assert not hasattr(result, "authorize")
    assert all("SUPPRESS" not in tier.value and "REUSE" not in tier.value for tier in result.matches[0].context_tiers)


def test_all_versioned_advisory_contracts_strict_round_trip() -> None:
    current = _representation("8" * 64)
    historical = _representation("9" * 64)
    index = only_build_research_advisory_index(PROJECTION, CUT, (historical,))
    policy = _policy()
    query = _query(current, index, policy)
    result = only_query_near_duplicates(
        current=current,
        query=query,
        index=index,
        policy=policy,
        source_verifier=_Verifier(historical),
    )
    pairs = (
        (OnlyResearchAdvisoryRepresentationV1, historical),
        (OnlyNearDuplicateThresholdPolicyV1, policy),
        (OnlyNearDuplicateQueryV1, query),
        (OnlyResearchAdvisoryIndexV1, index),
        (OnlyNearDuplicateMatchV1, result.matches[0]),
        (OnlyNearDuplicateResultV1, result),
    )

    for contract, value in pairs:
        assert contract.from_dict(value.to_dict()) == value
    assert (
        OnlyResearchAdvisoryRepresentationV1.from_dict(historical.to_dict()).representation_fingerprint
        == historical.representation_fingerprint
    )
    assert (
        OnlyNearDuplicateThresholdPolicyV1.from_dict(policy.to_dict()).policy_fingerprint == policy.policy_fingerprint
    )
    assert OnlyNearDuplicateQueryV1.from_dict(query.to_dict()).query_fingerprint == query.query_fingerprint
    assert OnlyResearchAdvisoryIndexV1.from_dict(index.to_dict()).index_build_revision == index.index_build_revision
    assert OnlyNearDuplicateResultV1.from_dict(result.to_dict()).result_fingerprint == result.result_fingerprint


@pytest.mark.parametrize(
    ("contract", "field", "bad"),
    (
        (OnlyResearchAdvisoryRepresentationV1, "representation_fingerprint", "0" * 64),
        (OnlyNearDuplicateThresholdPolicyV1, "policy_fingerprint", "0" * 64),
        (OnlyNearDuplicateThresholdPolicyV1, "minimum_retrieval_score", "0.50"),
        (OnlyNearDuplicateThresholdPolicyV1, "schema_version", 2),
        (OnlyNearDuplicateQueryV1, "query_fingerprint", "0" * 64),
        (OnlyNearDuplicateQueryV1, "retrieval_algorithm_id", "UNKNOWN"),
        (OnlyResearchAdvisoryIndexV1, "index_build_revision", "0" * 64),
        (OnlyNearDuplicateResultV1, "result_fingerprint", "0" * 64),
        (OnlyNearDuplicateResultV1, "status", "UNKNOWN"),
    ),
)
def test_strict_load_rejects_tampering(contract, field: str, bad: object) -> None:  # type: ignore[no-untyped-def]
    current = _representation("8" * 64)
    historical = _representation("9" * 64)
    index = only_build_research_advisory_index(PROJECTION, CUT, (historical,))
    policy = _policy()
    query = _query(current, index, policy)
    result = only_query_near_duplicates(
        current=current,
        query=query,
        index=index,
        policy=policy,
        source_verifier=_Verifier(historical),
    )
    values = {
        OnlyResearchAdvisoryRepresentationV1: historical,
        OnlyNearDuplicateThresholdPolicyV1: policy,
        OnlyNearDuplicateQueryV1: query,
        OnlyResearchAdvisoryIndexV1: index,
        OnlyNearDuplicateResultV1: result,
    }
    payload = values[contract].to_dict()
    payload[field] = bad

    with pytest.raises(ValueError):
        contract.from_dict(payload)


def test_strict_load_rejects_shape_order_duplicate_and_invalid_score() -> None:
    historical = _representation("9" * 64)
    index = only_build_research_advisory_index(PROJECTION, CUT, (historical,))
    extra = historical.to_dict()
    extra["extra"] = True
    missing = _policy().to_dict()
    missing.pop("maximum_results")
    duplicate = index.to_dict()
    duplicate["representations"] = [historical.to_dict(), historical.to_dict()]

    with pytest.raises(ValueError):
        OnlyResearchAdvisoryRepresentationV1.from_dict(extra)
    with pytest.raises(ValueError):
        OnlyNearDuplicateThresholdPolicyV1.from_dict(missing)
    with pytest.raises(ValueError):
        OnlyResearchAdvisoryIndexV1.from_dict(duplicate)

    result = only_query_near_duplicates(
        current=_representation("8" * 64),
        query=_query(_representation("8" * 64), index),
        index=index,
        policy=_policy(),
        source_verifier=_Verifier(historical),
    )
    match = result.matches[0].to_dict()
    match["score"] = "1.1"
    with pytest.raises(ValueError):
        OnlyNearDuplicateMatchV1.from_dict(match)
    match = result.matches[0].to_dict()
    match["context_tiers"] = list(reversed(match["context_tiers"]))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        OnlyNearDuplicateMatchV1.from_dict(match)
    match = result.matches[0].to_dict()
    match["context_tiers"] = ["HARD_REUSE_ELIGIBLE"]
    with pytest.raises(ValueError):
        OnlyNearDuplicateMatchV1.from_dict(match)
    with pytest.raises(ValueError, match="duplicate sources"):
        replace(result, matches=(result.matches[0], result.matches[0]))


def test_persisted_result_is_exactly_inspectable_without_todays_index() -> None:
    current = _representation("8" * 64)
    historical = _representation("9" * 64)
    index = only_build_research_advisory_index(PROJECTION, CUT, (historical,))
    result = only_query_near_duplicates(
        current=current,
        query=_query(current, index),
        index=index,
        policy=_policy(),
        source_verifier=_Verifier(historical),
    )
    persisted = result.to_dict()
    today = only_build_research_advisory_index(PROJECTION, CUT, ())

    loaded = OnlyNearDuplicateResultV1.from_dict(persisted)

    assert today.index_build_revision != loaded.index_build_revision
    assert loaded == result
    assert loaded.result_fingerprint == result.result_fingerprint


class _CutReader:
    def __init__(self, cut: OnlySourceClosedCutV1, observations: tuple[OnlySourceObservationV1, ...] = ()) -> None:
        self.cut = cut
        self.observations = observations
        self.unavailable = False

    def load_closed_cut_verified(self, fingerprint: str) -> OnlySourceClosedCutV1:
        if self.unavailable:
            raise RuntimeError("source unavailable")
        assert fingerprint == self.cut.cut_fingerprint
        return self.cut

    def iter_closed_cut_observations_verified(self, fingerprint: str) -> tuple[OnlySourceObservationV1, ...]:
        if self.unavailable:
            raise RuntimeError("source unavailable")
        assert fingerprint == self.cut.cut_fingerprint
        return self.observations


def _source_driven_case(tmp_path: Path):  # type: ignore[no-untyped-def]
    graph = factor_graph("HIGHER_IS_BETTER")
    specification = scientific_specification("a" * 64)
    node = next(item for item in graph.ordered_nodes if item.definition.type_id == "example.factor.momentum")
    result_locator, result_identity, run_identity = "3" * 64, "7" * 64, "8" * 64
    calculation = "c" * 64
    run_id = "00000000-0000-4000-8000-000000000001"
    result_payload = {
        "dataset_snapshot_fingerprint": specification.dataset_snapshot_fingerprint,
        "statistics_results": [{"statistics_fingerprint": "4" * 64, "statistics_result_fingerprint": "5" * 64}],
        "plan": {
            "calculations": [{"calculation_fingerprint": calculation, "graph_fingerprint": graph.fingerprint}],
            "candidates": [
                {
                    "candidate_fingerprint": "e" * 64,
                    "graph_fingerprint": graph.fingerprint,
                    "statistics_fingerprints": ["4" * 64],
                }
            ],
            "published_series": [
                {
                    "candidate_fingerprint": "e" * 64,
                    "node_fingerprint": node.fingerprint,
                    "output_name": "factor_value",
                }
            ],
            "signals": [],
        },
    }
    run_payload = {
        "source_row": {
            "run_id": run_id,
            "revision": 1,
            "state": "COMPLETED",
            "specification_fingerprint": specification.specification_fingerprint,
            "specification_payload": json.dumps(specification.to_dict()),
            "research_result_fingerprint": result_identity,
            "artifact_content_fingerprint": "d" * 64,
            "authoring_provenance": None,
            "calculation_execution_evidence_fingerprints": [],
        }
    }
    readers = {family: _CutReader(OnlySourceClosedCutV1(family, 1, ())) for family in MANDATORY_FAMILIES}
    for family, locator, identity, payload in (
        ("RESEARCH_RESULT", result_locator, result_identity, result_payload),
        ("RESEARCH_RUN", "00000000000000000001", run_identity, run_payload),
        (
            "RESEARCH_STATISTICS",
            "5" * 64,
            "5" * 64,
            {"statistics_fingerprint": "4" * 64, "statistics_result_fingerprint": "5" * 64},
        ),
    ):
        content = only_canonical_fingerprint(payload)
        cut = OnlySourceClosedCutV1(family, 1, (OnlySourceCutEntryV1(locator, identity, content),))
        readers[family] = _CutReader(
            cut,
            (OnlySourceObservationV1(family, 1, cut.cut_fingerprint, locator, identity, content, payload),),
        )
    manifest = OnlyExperimentMemorySourceCutManifestV1.from_cuts([reader.cut for reader in readers.values()])
    result_observation = readers["RESEARCH_RESULT"].observations[0]
    run_observation = readers["RESEARCH_RUN"].observations[0]
    result_ref = OnlyMemorySourceRefV1.from_observation(result_observation)
    run_ref = OnlyMemorySourceRefV1.from_observation(run_observation)
    statistics_ref = OnlyMemorySourceRefV1.from_observation(readers["RESEARCH_STATISTICS"].observations[0])
    record = OnlyMemoryProjectionRecordV1(
        "EvaluationProjectionRecord",
        {
            "candidate_fingerprint": "e" * 64,
            "graph_fingerprint": graph.fingerprint,
            "candidate_node_fingerprint": node.fingerprint,
            "output_name": "factor_value",
            "dataset_snapshot_fingerprint": specification.dataset_snapshot_fingerprint,
            "research_result_locator": result_locator,
            "research_result_fingerprint": result_identity,
            "statistics_references": [{"statistics_fingerprint": "4" * 64, "statistics_result_fingerprint": "5" * 64}],
            "run_evaluation_closures": [
                {
                    "run_id": run_id,
                    "run_revision": 1,
                    "run_state": "COMPLETED",
                    "specification_fingerprint": specification.specification_fingerprint,
                    "research_result_fingerprint": result_identity,
                    "artifact_content_fingerprint": "d" * 64,
                    "catalog_generation_fingerprint": "5" * 64,
                    "runtime_generation_fingerprint": "6" * 64,
                    "authoring_generation_fingerprint": None,
                    "calculation_execution_evidence_fingerprints": [],
                    "run_source_ref": run_ref.to_dict(),
                    "search_lineage": None,
                }
            ],
        },
        tuple(sorted((result_ref, run_ref, statistics_ref), key=lambda item: (item.source_family, item.locator))),
    )
    projection = OnlyExperimentMemoryProjectionV1(manifest, (record,))
    store = OnlyExperimentMemoryRevisionStore(tmp_path / "experiment-memory")
    store._publish_and_activate(projection)
    calculation_result = SimpleNamespace(
        manifest=SimpleNamespace(
            calculation_fingerprint=calculation,
            calculation_graph_fingerprint=graph.fingerprint,
            calculation_graph=graph,
        )
    )
    calculations = SimpleNamespace(
        load_verified=lambda identity: calculation_result if identity == calculation else None
    )
    exact_values = {
        ("DATASET_SNAPSHOT", specification.dataset_snapshot_fingerprint): {
            "snapshot_fingerprint": specification.dataset_snapshot_fingerprint
        },
        ("CALCULATION_GRAPH", graph.fingerprint): {"graph_fingerprint": graph.fingerprint},
        ("RESEARCH_SPECIFICATION", specification.specification_fingerprint): specification.to_dict(),
        ("RUNTIME_WORK_BINDING", run_id): {
            "work_id": run_id,
            "runtime_generation_fingerprint": "6" * 64,
            "catalog_generation_fingerprint": "5" * 64,
        },
    }
    references = SimpleNamespace(
        for_observations=lambda _observations: lambda kind, identity: exact_values[(kind, identity)]
    )
    return store, readers, references, calculations, graph, specification, projection


def test_source_driven_rebuild_and_production_verification_are_exact(tmp_path: Path) -> None:
    store, readers, references, calculations, graph, specification, projection = _source_driven_case(tmp_path)
    builder = OnlyExperimentMemoryAdvisoryProjectionBuilder(store, readers, references, calculations)
    first_index = builder.build_index(projection.revision_fingerprint)
    historical = first_index.representations[0]
    current = only_build_research_advisory_representation(
        subject=OnlyExactEvaluationIntentSubjectV1(
            graph.fingerprint,
            next(
                item for item in graph.ordered_nodes if item.definition.type_id == "example.factor.momentum"
            ).fingerprint,
            "factor_value",
            "f" * 64,
            specification.dataset_snapshot_fingerprint,
            specification.specification_fingerprint,
            "3" * 64,
            ("4" * 64,),
            "5" * 64,
            "6" * 64,
            None,
        ),
        graph=graph,
        specification=specification,
        source_ref=OnlyResearchAdvisorySourceRefV1("CURRENT", "current", "current", "1" * 64),
        projection_revision=projection.revision_fingerprint,
        source_cut_fingerprint=projection.source_manifest.manifest_fingerprint,
    )
    first_result = only_query_near_duplicates(
        current=current,
        query=_query(current, first_index),
        index=first_index,
        policy=_policy(),
        source_verifier=builder,
    )

    shutil.rmtree(tmp_path / "experiment-memory")
    rebuilt_store = OnlyExperimentMemoryRevisionStore(tmp_path / "experiment-memory")
    rebuilt_store._publish_and_activate(projection)
    rebuilt_builder = OnlyExperimentMemoryAdvisoryProjectionBuilder(rebuilt_store, readers, references, calculations)
    rebuilt_index = rebuilt_builder.build_index(projection.revision_fingerprint)
    rebuilt_result = only_query_near_duplicates(
        current=current,
        query=_query(current, rebuilt_index),
        index=rebuilt_index,
        policy=_policy(),
        source_verifier=rebuilt_builder,
    )

    assert rebuilt_index == first_index
    assert rebuilt_index.index_build_revision == first_index.index_build_revision
    assert rebuilt_result == first_result
    assert rebuilt_result.result_fingerprint == first_result.result_fingerprint
    assert (
        rebuilt_builder.load_representation_verified(
            historical.source_ref, projection.revision_fingerprint, historical.representation_schema_version
        )
        == historical
    )


def test_production_verifier_distinguishes_missing_unavailable_and_revision_mismatch(tmp_path: Path) -> None:
    store, readers, references, calculations, _, _, projection = _source_driven_case(tmp_path)
    builder = OnlyExperimentMemoryAdvisoryProjectionBuilder(store, readers, references, calculations)
    index = builder.build_index(projection.revision_fingerprint)
    current = replace(
        index.representations[0], source_ref=OnlyResearchAdvisorySourceRefV1("CURRENT", "x", "x", "1" * 64)
    )
    query = _query(current, index)

    readers["RESEARCH_RUN"].observations = ()
    partial = only_query_near_duplicates(
        current=current, query=query, index=index, policy=_policy(), source_verifier=builder
    )
    assert partial.status is OnlyNearDuplicateResultStatus.ADVISORY_PARTIAL

    _, unavailable_readers, unavailable_references, unavailable_calculations, _, _, _ = _source_driven_case(
        tmp_path / "other"
    )
    unavailable_readers["RESEARCH_RUN"].unavailable = True
    unavailable_builder = OnlyExperimentMemoryAdvisoryProjectionBuilder(
        OnlyExperimentMemoryRevisionStore(tmp_path / "other" / "experiment-memory"),
        unavailable_readers,
        unavailable_references,
        unavailable_calculations,
    )
    unavailable = only_query_near_duplicates(
        current=current, query=query, index=index, policy=_policy(), source_verifier=unavailable_builder
    )
    assert unavailable.status is OnlyNearDuplicateResultStatus.ADVISORY_UNAVAILABLE

    mismatched = replace(
        index.representations[0],
        source_ref=replace(index.representations[0].source_ref, source_revision="0" * 64),
    )
    mismatch_index = only_build_research_advisory_index(
        projection.revision_fingerprint, projection.source_manifest.manifest_fingerprint, (mismatched,)
    )
    mismatch = only_query_near_duplicates(
        current=current,
        query=_query(current, mismatch_index),
        index=mismatch_index,
        policy=_policy(),
        source_verifier=OnlyExperimentMemoryAdvisoryProjectionBuilder(
            store,
            _source_driven_case(tmp_path / "fresh")[1],
            references,
            calculations,
        ),
    )
    assert mismatch.status is OnlyNearDuplicateResultStatus.ADVISORY_PARTIAL


def test_source_builder_rejects_an_evaluation_without_owning_run_context(tmp_path: Path) -> None:
    _, readers, references, calculations, _, _, projection = _source_driven_case(tmp_path / "valid")
    record = projection.records[0]
    facets = dict(record.facets)
    facets["run_evaluation_closures"] = []
    incomplete = OnlyExperimentMemoryProjectionV1(
        projection.source_manifest,
        (OnlyMemoryProjectionRecordV1(record.kind, facets, record.source_refs),),
    )
    store = OnlyExperimentMemoryRevisionStore(tmp_path / "incomplete" / "experiment-memory")
    store._publish_and_activate(incomplete)

    with pytest.raises(ValueError, match="projection is incomplete"):
        OnlyExperimentMemoryAdvisoryProjectionBuilder(store, readers, references, calculations).build_index(
            incomplete.revision_fingerprint
        )
