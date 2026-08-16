from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from onlyalpha.research import OnlyResearchArtifactError, OnlyResearchArtifactMaterializer
from tests.research.artifact.support import artifact_case


class _ResultStore:
    def __init__(self, result):  # type: ignore[no-untyped-def]
        self.result = result

    def load_verified(self, _fingerprint: str):  # type: ignore[no-untyped-def]
        return self.result


class _StatisticsStore:
    def __init__(self, values):  # type: ignore[no-untyped-def]
        self.values = values
        self.loaded: list[str] = []

    def load_verified(self, fingerprint: str):  # type: ignore[no-untyped-def]
        self.loaded.append(fingerprint)
        return self.values[fingerprint]


def test_materializer_uses_exact_research_membership_and_canonical_projection(tmp_path) -> None:
    plan, research_result, statistics_store, _, candidate, _ = artifact_case(tmp_path)

    assert tuple(item.statistics_fingerprint for item in candidate.statistics_results) == plan.statistics_fingerprints
    assert {row.statistics_fingerprint for row in candidate.rows} == set(plan.statistics_fingerprints)
    assert candidate.rows == tuple(sorted(candidate.rows))
    assert candidate.research_result_fingerprint == research_result.manifest.research_result_fingerprint
    assert sum(item.row_count for item in candidate.statistics_results) == len(candidate.rows)
    for item in candidate.statistics_results:
        assert statistics_store.load_verified(item.statistics_fingerprint).manifest.plan == item.plan


def test_materializer_enumeration_order_cannot_change_identity(tmp_path) -> None:
    _, research_result, statistics_store, _, candidate, _ = artifact_case(tmp_path)
    references = tuple(reversed(research_result.manifest.statistics_results))
    reordered_manifest = replace(
        research_result.manifest,
        statistics_results=tuple(sorted(references)),
    )
    materializer = OnlyResearchArtifactMaterializer(
        _ResultStore(replace(research_result, manifest=reordered_manifest)), statistics_store
    )

    assert materializer.materialize(reordered_manifest.research_result_plan_fingerprint) == candidate


@pytest.mark.parametrize("mutation", ("dataset", "result", "content", "plan", "rows"))
def test_materializer_revalidates_every_upstream_identity_and_fails_whole_projection(tmp_path, mutation: str) -> None:
    plan, research_result, statistics_store, _, _, _ = artifact_case(tmp_path)
    reference = research_result.manifest.statistics_results[0]
    valid = statistics_store.load_verified(reference.statistics_fingerprint)
    manifest = valid.manifest
    if mutation == "dataset":
        changed = replace(valid, manifest=replace(manifest, dataset_snapshot_fingerprint="e" * 64))
    elif mutation == "result":
        changed = replace(
            valid, manifest=SimpleNamespace(**(manifest.to_dict() | {"statistics_result_fingerprint": "e" * 64}))
        )
    elif mutation == "content":
        changed = replace(
            valid, manifest=SimpleNamespace(**(manifest.to_dict() | {"result_content_fingerprint": "e" * 64}))
        )
    elif mutation == "plan":
        changed = replace(
            valid, manifest=SimpleNamespace(**(manifest.to_dict() | {"statistics_fingerprint": "e" * 64}))
        )
    else:
        changed = replace(valid, rows=tuple(reversed(valid.rows)))
    values = {
        item.statistics_fingerprint: statistics_store.load_verified(item.statistics_fingerprint)
        for item in research_result.manifest.statistics_results
    }
    values[reference.statistics_fingerprint] = changed
    materializer = OnlyResearchArtifactMaterializer(_ResultStore(research_result), _StatisticsStore(values))

    with pytest.raises(OnlyResearchArtifactError) as raised:
        materializer.materialize(plan.fingerprint)
    assert raised.value.code == "ARTIFACT_INVALID"


def test_missing_or_corrupt_upstream_never_produces_partial_candidate(tmp_path) -> None:
    plan, research_result, _, _, _, _ = artifact_case(tmp_path)
    materializer = OnlyResearchArtifactMaterializer(_ResultStore(research_result), _StatisticsStore({}))
    with pytest.raises(OnlyResearchArtifactError) as raised:
        materializer.materialize(plan.fingerprint)
    assert raised.value.code == "ARTIFACT_INVALID"
