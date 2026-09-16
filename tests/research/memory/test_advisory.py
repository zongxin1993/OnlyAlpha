from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from onlyalpha.research.evaluation.subject import OnlyExactEvaluationIntentSubjectV1
from onlyalpha.research.memory.advisory import (
    OnlyNearDuplicateContextTier,
    OnlyNearDuplicateQueryV1,
    OnlyNearDuplicateResultStatus,
    OnlyNearDuplicateThresholdPolicyV1,
    OnlyResearchAdvisorySourceRefV1,
    OnlyResearchAdvisoryUnavailableError,
    only_build_research_advisory_index,
    only_build_research_advisory_representation,
    only_query_near_duplicates,
)
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
    assert OnlyNearDuplicateContextTier.COMPARABLE in first.matches[0].context_tiers
    assert OnlyNearDuplicateContextTier.ADVISORY_SIMILAR in first.matches[0].context_tiers
    assert "PARAMETERS" in first.matches[0].different
    assert OnlyNearDuplicateContextTier.HARD_REUSE_ELIGIBLE not in first.matches[0].context_tiers
    assert OnlyNearDuplicateContextTier.HARD_SUPPRESSION_ELIGIBLE not in first.matches[0].context_tiers


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
    assert OnlyNearDuplicateContextTier.RETRIEVABLE in result.matches[0].context_tiers
    assert OnlyNearDuplicateContextTier.ADVISORY_SIMILAR in result.matches[0].context_tiers
    assert OnlyNearDuplicateContextTier.COMPARABLE not in result.matches[0].context_tiers
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
    assert OnlyNearDuplicateContextTier.COMPARABLE not in result.matches[0].context_tiers
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
