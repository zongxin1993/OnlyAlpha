from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.experiment import (
    OnlyJsonSearchProvenanceStore,
    OnlySearchCommitDisposition,
    OnlySearchExperimentManifestV1,
    OnlySearchFailureCode,
    OnlySearchIterationDisposition,
    OnlySearchIterationPlanV1,
    OnlySearchIterationResultV1,
    OnlySearchProvenanceError,
    OnlySearchProvenanceStoreError,
)

from .support import experiment, fingerprint, plan


@dataclass(frozen=True)
class FakeCatalog:
    generation_fingerprint: str


class FakeCatalogReader:
    def __init__(self, *fingerprints: str) -> None:
        self.values = {value: FakeCatalog(value) for value in fingerprints}

    def generation(self, fingerprint: str) -> FakeCatalog:
        return self.values[fingerprint]


@dataclass(frozen=True)
class FakeSnapshot:
    snapshot_fingerprint: str


@dataclass(frozen=True)
class FakeDataset:
    snapshot: FakeSnapshot


class FakeDatasetReader:
    def __init__(self, *fingerprints: str) -> None:
        self.values = {value: FakeDataset(FakeSnapshot(value)) for value in fingerprints}

    def load_verified_table(self, fingerprint: str) -> FakeDataset:
        return self.values[fingerprint]


@dataclass(frozen=True)
class FakeCandidate:
    candidate_fingerprint: str


class FakeCandidateReader:
    def __init__(self, *fingerprints: str) -> None:
        self.values = {value: FakeCandidate(value) for value in fingerprints}
        self.loads = 0

    def load_verified(self, fingerprint: str) -> FakeCandidate:
        self.loads += 1
        return self.values[fingerprint]


@dataclass(frozen=True)
class FakeResearchPlan:
    candidates: tuple[FakeCandidate, ...]


@dataclass(frozen=True)
class FakeResearchManifest:
    research_result_fingerprint: str
    dataset_snapshot_fingerprint: str
    plan: FakeResearchPlan


@dataclass(frozen=True)
class FakeResearchResult:
    manifest: FakeResearchManifest


class FakeResearchResultReader:
    def __init__(self, fingerprint: str, candidate_fingerprint: str, dataset_fingerprint: str) -> None:
        self.values = {
            fingerprint: FakeResearchResult(
                FakeResearchManifest(
                    fingerprint,
                    dataset_fingerprint,
                    FakeResearchPlan((FakeCandidate(candidate_fingerprint),)),
                )
            )
        }
        self.loads = 0

    def load_verified(self, fingerprint: str) -> FakeResearchResult:
        self.loads += 1
        return self.values[fingerprint]


@dataclass(frozen=True)
class FakeEvidence:
    evidence_fingerprint: str


@dataclass(frozen=True)
class FakeDecision:
    decision_fingerprint: str
    evidence: tuple[FakeEvidence, ...]


class FakeDecisionReader:
    def __init__(self, fingerprint: str, research_result_fingerprint: str) -> None:
        self.values = {fingerprint: FakeDecision(fingerprint, (FakeEvidence(research_result_fingerprint),))}
        self.loads = 0

    def load_verified(self, fingerprint: str) -> FakeDecision:
        self.loads += 1
        return self.values[fingerprint]


def stores(
    root: Path,
    *,
    candidate_fingerprint: str = fingerprint("c"),
    research_result_fingerprint: str = fingerprint("d"),
    decision_fingerprint: str = fingerprint("e"),
) -> tuple[
    OnlyJsonSearchProvenanceStore,
    FakeCandidateReader,
    FakeResearchResultReader,
    FakeDecisionReader,
]:
    value = experiment()
    candidates = FakeCandidateReader(candidate_fingerprint)
    research = FakeResearchResultReader(
        research_result_fingerprint,
        candidate_fingerprint,
        value.dataset_snapshot_fingerprint,
    )
    decisions = FakeDecisionReader(decision_fingerprint, research_result_fingerprint)
    return (
        OnlyJsonSearchProvenanceStore(
            root,
            catalogs=FakeCatalogReader(value.catalog_generation_fingerprint),
            datasets=FakeDatasetReader(value.dataset_snapshot_fingerprint),
            candidates=candidates,
            research_results=research,
            qualification_decisions=decisions,
        ),
        candidates,
        research,
        decisions,
    )


def qualification_result(value: OnlySearchIterationPlanV1) -> OnlySearchIterationResultV1:
    return OnlySearchIterationResultV1(
        value.iteration_plan_fingerprint,
        fingerprint("c"),
        True,
        fingerprint("d"),
        True,
        fingerprint("e"),
        OnlySearchIterationDisposition.QUALIFICATION_DECISION_RECORDED,
        None,
    )


def test_commit_load_and_reuse_all_three_record_types(tmp_path: Path) -> None:
    store, candidates, research, decisions = stores(tmp_path)
    search = experiment()
    iteration = plan(search.experiment_fingerprint)
    result = qualification_result(iteration)

    for first, second, value in (
        (store.commit_experiment(search), store.commit_experiment(search), search.experiment_fingerprint),
        (
            store.commit_iteration_plan(iteration),
            store.commit_iteration_plan(iteration),
            iteration.iteration_plan_fingerprint,
        ),
        (
            store.commit_iteration_result(result),
            store.commit_iteration_result(result),
            result.iteration_result_fingerprint,
        ),
    ):
        assert first.disposition is OnlySearchCommitDisposition.CREATED
        assert second.disposition is OnlySearchCommitDisposition.REUSED
        assert first.fingerprint == second.fingerprint == value

    assert store.load_experiment_verified(search.experiment_fingerprint) == search
    assert store.load_iteration_plan_verified(iteration.iteration_plan_fingerprint) == iteration
    assert store.load_iteration_result_verified(result.iteration_result_fingerprint) == result
    assert candidates.loads > 0 and research.loads > 0 and decisions.loads > 0


def test_one_plan_cannot_have_two_terminal_results(tmp_path: Path) -> None:
    store, _, _, _ = stores(tmp_path)
    search = experiment()
    iteration = plan(search.experiment_fingerprint)
    store.commit_experiment(search)
    store.commit_iteration_plan(iteration)
    first = OnlySearchIterationResultV1(
        iteration.iteration_plan_fingerprint,
        fingerprint("c"),
        False,
        None,
        False,
        None,
        OnlySearchIterationDisposition.CANDIDATE_BOUND,
        None,
    )
    second = replace(
        first,
        disposition=OnlySearchIterationDisposition.FAILED,
        failure_code=OnlySearchFailureCode.RESEARCH_SUBMISSION_FAILED,
    )
    store.commit_iteration_result(first)
    with pytest.raises(OnlySearchProvenanceStoreError, match="SEARCH_ITERATION_TERMINAL_RESULT_CONFLICT"):
        store.commit_iteration_result(second)


def test_concurrent_different_terminal_results_fail_closed(tmp_path: Path) -> None:
    first_store, _, _, _ = stores(tmp_path)
    second_store, _, _, _ = stores(tmp_path)
    search = experiment()
    iteration = plan(search.experiment_fingerprint)
    first_store.commit_experiment(search)
    first_store.commit_iteration_plan(iteration)
    first = OnlySearchIterationResultV1(
        iteration.iteration_plan_fingerprint,
        fingerprint("c"),
        False,
        None,
        False,
        None,
        OnlySearchIterationDisposition.CANDIDATE_BOUND,
        None,
    )
    second = replace(
        first,
        disposition=OnlySearchIterationDisposition.FAILED,
        failure_code=OnlySearchFailureCode.RESEARCH_SUBMISSION_FAILED,
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (
            pool.submit(first_store.commit_iteration_result, first),
            pool.submit(second_store.commit_iteration_result, second),
        )
        outcomes = []
        failures = []
        for future in futures:
            try:
                outcomes.append(future.result())
            except OnlySearchProvenanceStoreError as exc:
                failures.append(exc)
    assert len(outcomes) == 1
    assert len(failures) == 1
    assert failures[0].code == "SEARCH_ITERATION_TERMINAL_RESULT_CONFLICT"


def test_external_references_fail_closed_and_are_not_recomputed(tmp_path: Path) -> None:
    store, _, research, decisions = stores(tmp_path)
    search = experiment()
    iteration = plan(search.experiment_fingerprint)
    store.commit_experiment(search)
    store.commit_iteration_plan(iteration)
    store.commit_iteration_result(qualification_result(iteration))
    assert not hasattr(research, "calculate")
    assert not hasattr(decisions, "evaluate")

    missing_store = OnlyJsonSearchProvenanceStore(
        tmp_path / "missing",
        catalogs=FakeCatalogReader(search.catalog_generation_fingerprint),
        datasets=FakeDatasetReader(search.dataset_snapshot_fingerprint),
    )
    missing_store.commit_experiment(search)
    missing_store.commit_iteration_plan(iteration)
    with pytest.raises(OnlySearchProvenanceError, match="SEARCH_EXTERNAL_REFERENCE_READER_UNAVAILABLE"):
        missing_store.commit_iteration_result(qualification_result(iteration))


def test_missing_catalog_dataset_candidate_research_and_qualification_fail_closed(tmp_path: Path) -> None:
    search = experiment()
    no_catalog = OnlyJsonSearchProvenanceStore(
        tmp_path / "catalog",
        catalogs=FakeCatalogReader(),
        datasets=FakeDatasetReader(search.dataset_snapshot_fingerprint),
    )
    with pytest.raises(OnlySearchProvenanceError, match="SEARCH_CATALOG_GENERATION_REFERENCE_INVALID"):
        no_catalog.commit_experiment(search)

    no_dataset = OnlyJsonSearchProvenanceStore(
        tmp_path / "dataset",
        catalogs=FakeCatalogReader(search.catalog_generation_fingerprint),
        datasets=FakeDatasetReader(),
    )
    with pytest.raises(OnlySearchProvenanceError, match="SEARCH_DATASET_SNAPSHOT_REFERENCE_INVALID"):
        no_dataset.commit_experiment(search)

    store, candidates, research, decisions = stores(tmp_path / "result")
    iteration = plan(search.experiment_fingerprint)
    store.commit_experiment(search)
    store.commit_iteration_plan(iteration)
    candidates.values.clear()
    with pytest.raises(OnlySearchProvenanceError, match="SEARCH_CANDIDATE_REFERENCE_INVALID"):
        store.commit_iteration_result(qualification_result(iteration))
    candidates.values[fingerprint("c")] = FakeCandidate(fingerprint("c"))
    research.values.clear()
    with pytest.raises(OnlySearchProvenanceError, match="SEARCH_RESEARCH_RESULT_REFERENCE_INVALID"):
        store.commit_iteration_result(qualification_result(iteration))
    research.values[fingerprint("d")] = FakeResearchResult(
        FakeResearchManifest(
            fingerprint("d"),
            fingerprint("f"),
            FakeResearchPlan((FakeCandidate(fingerprint("c")),)),
        )
    )
    with pytest.raises(OnlySearchProvenanceError, match="SEARCH_RESEARCH_RESULT_REFERENCE_INVALID"):
        store.commit_iteration_result(qualification_result(iteration))
    research.values[fingerprint("d")] = FakeResearchResult(
        FakeResearchManifest(
            fingerprint("d"),
            search.dataset_snapshot_fingerprint,
            FakeResearchPlan((FakeCandidate(fingerprint("c")),)),
        )
    )
    decisions.values.clear()
    with pytest.raises(OnlySearchProvenanceError, match="SEARCH_QUALIFICATION_DECISION_REFERENCE_INVALID"):
        store.commit_iteration_result(qualification_result(iteration))


def test_parent_result_must_be_committed_and_belong_to_same_experiment(tmp_path: Path) -> None:
    store, _, _, _ = stores(tmp_path)
    first = experiment()
    second = replace(first, seed=99)
    store.commit_experiment(first)
    store.commit_experiment(second)
    root = plan(first.experiment_fingerprint, 0)
    store.commit_iteration_plan(root)
    root_result = OnlySearchIterationResultV1(
        root.iteration_plan_fingerprint,
        None,
        False,
        None,
        False,
        None,
        OnlySearchIterationDisposition.FAILED,
        OnlySearchFailureCode.CANDIDATE_BINDING_FAILED,
    )
    child = plan(
        first.experiment_fingerprint,
        1,
        parent_iteration_result_fingerprint=root_result.iteration_result_fingerprint,
    )
    with pytest.raises(OnlySearchProvenanceError, match="SEARCH_ITERATION_PARENT_INVALID"):
        store.commit_iteration_plan(child)
    store.commit_iteration_result(root_result)
    store.commit_iteration_plan(child)
    cross = plan(
        second.experiment_fingerprint,
        1,
        parent_iteration_result_fingerprint=root_result.iteration_result_fingerprint,
    )
    with pytest.raises(OnlySearchProvenanceError, match="SEARCH_ITERATION_CROSS_EXPERIMENT_PARENT"):
        store.commit_iteration_plan(cross)


@pytest.mark.parametrize(
    ("category", "fingerprint_attribute"),
    (
        ("experiments", "experiment_fingerprint"),
        ("iteration-plans", "iteration_plan_fingerprint"),
        ("iteration-results", "iteration_result_fingerprint"),
    ),
)
def test_corruption_fingerprint_mismatch_and_unknown_schema_fail_closed(
    tmp_path: Path,
    category: str,
    fingerprint_attribute: str,
) -> None:
    store, _, _, _ = stores(tmp_path)
    search = experiment()
    iteration = plan(search.experiment_fingerprint)
    result = qualification_result(iteration)
    store.commit_experiment(search)
    store.commit_iteration_plan(iteration)
    store.commit_iteration_result(result)
    value = {
        "experiments": search,
        "iteration-plans": iteration,
        "iteration-results": result,
    }[category]
    fingerprint_value = getattr(value, fingerprint_attribute)
    manifest = tmp_path / "research" / "search-provenance" / category / "sha256" / fingerprint_value[:2]
    manifest = manifest / fingerprint_value / "manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["schema_version"] = 999
    manifest.write_text(only_canonical_json(payload), encoding="utf-8")
    loader = {
        "experiments": store.load_experiment_verified,
        "iteration-plans": store.load_iteration_plan_verified,
        "iteration-results": store.load_iteration_result_verified,
    }[category]
    with pytest.raises(OnlySearchProvenanceStoreError, match="CORRUPT"):
        loader(fingerprint_value)


def test_byte_corruption_and_fingerprint_mismatch_fail_closed(tmp_path: Path) -> None:
    store, _, _, _ = stores(tmp_path)
    search = experiment()
    store.commit_experiment(search)
    manifest = (
        tmp_path
        / "research"
        / "search-provenance"
        / "experiments"
        / "sha256"
        / search.experiment_fingerprint[:2]
        / search.experiment_fingerprint
        / "manifest.json"
    )
    original = manifest.read_text(encoding="utf-8")
    manifest.write_text("{not-json", encoding="utf-8")
    with pytest.raises(OnlySearchProvenanceStoreError, match="SEARCH_EXPERIMENT_CORRUPT"):
        store.load_experiment_verified(search.experiment_fingerprint)
    manifest.write_text(original, encoding="utf-8")
    payload = json.loads(original)
    payload["experiment_fingerprint"] = fingerprint("f")
    manifest.write_text(only_canonical_json(payload), encoding="utf-8")
    with pytest.raises(OnlySearchProvenanceStoreError, match="SEARCH_EXPERIMENT_CORRUPT"):
        store.load_experiment_verified(search.experiment_fingerprint)


def test_same_identity_with_different_semantic_content_is_conflict(tmp_path: Path) -> None:
    store, _, _, _ = stores(tmp_path)
    original = experiment()
    store.commit_experiment(original)

    class CollisionManifest(OnlySearchExperimentManifestV1):
        @property
        def experiment_fingerprint(self) -> str:
            return original.experiment_fingerprint

    changed = CollisionManifest(
        original.hypothesis,
        original.search_algorithm_binding,
        original.search_space_reference,
        original.randomness_mode,
        99,
        original.search_budget,
        original.catalog_generation_fingerprint,
        original.dataset_snapshot_fingerprint,
        original.workflow_binding,
        original.decision_engine_binding,
    )
    with pytest.raises(OnlySearchProvenanceStoreError, match="SEARCH_EXPERIMENT_CONFLICT"):
        store.commit_experiment(changed)


def test_unknown_discriminant_and_unsafe_symlink_fail_closed(tmp_path: Path) -> None:
    store, _, _, _ = stores(tmp_path)
    search = experiment()
    store.commit_experiment(search)
    manifest = (
        tmp_path
        / "research"
        / "search-provenance"
        / "experiments"
        / "sha256"
        / search.experiment_fingerprint[:2]
        / search.experiment_fingerprint
        / "manifest.json"
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["randomness_mode"] = "UNKNOWN"
    manifest.write_text(only_canonical_json(payload), encoding="utf-8")
    with pytest.raises(OnlySearchProvenanceStoreError, match="SEARCH_EXPERIMENT_CORRUPT"):
        store.load_experiment_verified(search.experiment_fingerprint)

    unsafe_root = tmp_path / "unsafe"
    unsafe_root.symlink_to(tmp_path / "actual", target_is_directory=True)
    unsafe_store, _, _, _ = stores(unsafe_root)
    with pytest.raises(OnlySearchProvenanceStoreError, match="SEARCH_PROVENANCE_UNSAFE_PATH"):
        unsafe_store.commit_experiment(search)


def test_record_manifest_symlink_fails_closed(tmp_path: Path) -> None:
    store, _, _, _ = stores(tmp_path)
    search = experiment()
    store.commit_experiment(search)
    record = (
        tmp_path
        / "research"
        / "search-provenance"
        / "experiments"
        / "sha256"
        / search.experiment_fingerprint[:2]
        / search.experiment_fingerprint
    )
    manifest = record / "manifest.json"
    alias_target = tmp_path / "alias.json"
    alias_target.write_text(manifest.read_text(encoding="utf-8"), encoding="utf-8")
    manifest.unlink()
    manifest.symlink_to(alias_target)
    with pytest.raises(OnlySearchProvenanceStoreError, match="SEARCH_EXPERIMENT_CORRUPT"):
        store.load_experiment_verified(search.experiment_fingerprint)


def test_store_has_no_mutation_or_latest_fuzzy_api(tmp_path: Path) -> None:
    store, _, _, _ = stores(tmp_path)
    forbidden = {
        "update",
        "replace",
        "delete",
        "latest_experiment",
        "latest_iteration",
        "nearest_proposal",
        "find_best_experiment",
        "search_similar_experiment",
    }
    assert forbidden.isdisjoint(dir(store))
