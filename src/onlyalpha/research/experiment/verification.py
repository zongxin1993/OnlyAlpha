"""Exact Search Experiment lineage and external-reference verification ports."""

from __future__ import annotations

from typing import Protocol

from .errors import OnlySearchProvenanceError
from .model import OnlySearchExperimentManifestV1, OnlySearchIterationPlanV1, OnlySearchIterationResultV1


class OnlySearchCatalogGenerationValue(Protocol):
    @property
    def generation_fingerprint(self) -> str: ...


class OnlySearchCatalogGenerationReader(Protocol):
    def generation(self, fingerprint: str) -> OnlySearchCatalogGenerationValue: ...


class OnlySearchDatasetSnapshotValue(Protocol):
    @property
    def snapshot_fingerprint(self) -> str: ...


class OnlySearchVerifiedDatasetValue(Protocol):
    @property
    def snapshot(self) -> OnlySearchDatasetSnapshotValue: ...


class OnlySearchDatasetReader(Protocol):
    def load_verified_table(self, snapshot_fingerprint: str) -> OnlySearchVerifiedDatasetValue: ...


class OnlySearchCandidateValue(Protocol):
    @property
    def candidate_fingerprint(self) -> str: ...


class OnlySearchCandidateReader(Protocol):
    def load_verified(self, candidate_fingerprint: str) -> OnlySearchCandidateValue: ...


class OnlySearchResearchResultPlanValue(Protocol):
    @property
    def candidates(self) -> tuple[OnlySearchCandidateValue, ...]: ...


class OnlySearchResearchResultManifestValue(Protocol):
    @property
    def research_result_fingerprint(self) -> str: ...

    @property
    def dataset_snapshot_fingerprint(self) -> str: ...

    @property
    def plan(self) -> OnlySearchResearchResultPlanValue: ...


class OnlySearchResearchResultValue(Protocol):
    @property
    def manifest(self) -> OnlySearchResearchResultManifestValue: ...


class OnlySearchResearchResultReader(Protocol):
    def load_verified(self, research_result_fingerprint: str) -> OnlySearchResearchResultValue: ...


class OnlySearchQualificationEvidenceValue(Protocol):
    @property
    def evidence_fingerprint(self) -> str: ...


class OnlySearchQualificationDecisionValue(Protocol):
    @property
    def decision_fingerprint(self) -> str: ...

    @property
    def evidence(self) -> tuple[OnlySearchQualificationEvidenceValue, ...]: ...


class OnlySearchQualificationDecisionReader(Protocol):
    def load_verified(self, decision_fingerprint: str) -> OnlySearchQualificationDecisionValue: ...


class OnlySearchExperimentReader(Protocol):
    def load_experiment_verified(self, experiment_fingerprint: str) -> OnlySearchExperimentManifestV1: ...


class OnlySearchIterationPlanReader(Protocol):
    def load_iteration_plan_verified(self, iteration_plan_fingerprint: str) -> OnlySearchIterationPlanV1: ...


class OnlySearchIterationResultReader(Protocol):
    def load_iteration_result_verified(self, iteration_result_fingerprint: str) -> OnlySearchIterationResultV1: ...


def verify_search_iteration_lineage(
    plan: OnlySearchIterationPlanV1,
    *,
    experiments: OnlySearchExperimentReader,
    plans: OnlySearchIterationPlanReader,
    results: OnlySearchIterationResultReader,
) -> None:
    """Prove that a Plan references only committed Result feedback in its own Experiment."""

    try:
        experiment = experiments.load_experiment_verified(plan.experiment_fingerprint)
        if experiment.experiment_fingerprint != plan.experiment_fingerprint:
            raise ValueError("Search Experiment reader returned a different identity")
        parent_fingerprint = plan.parent_iteration_result_fingerprint
        seen_results: set[str] = set()
        while parent_fingerprint is not None:
            if parent_fingerprint in seen_results:
                raise OnlySearchProvenanceError("SEARCH_ITERATION_LINEAGE_CYCLE", parent_fingerprint)
            seen_results.add(parent_fingerprint)
            parent_result = results.load_iteration_result_verified(parent_fingerprint)
            if parent_result.iteration_result_fingerprint != parent_fingerprint:
                raise ValueError("parent Result reader returned a different identity")
            parent_plan = plans.load_iteration_plan_verified(parent_result.iteration_plan_fingerprint)
            if parent_plan.iteration_plan_fingerprint == plan.iteration_plan_fingerprint:
                raise OnlySearchProvenanceError("SEARCH_ITERATION_SELF_PARENT", plan.iteration_plan_fingerprint)
            if parent_plan.experiment_fingerprint != plan.experiment_fingerprint:
                raise OnlySearchProvenanceError("SEARCH_ITERATION_CROSS_EXPERIMENT_PARENT", parent_fingerprint)
            parent_fingerprint = parent_plan.parent_iteration_result_fingerprint
    except OnlySearchProvenanceError as exc:
        if exc.code in {
            "SEARCH_ITERATION_LINEAGE_CYCLE",
            "SEARCH_ITERATION_SELF_PARENT",
            "SEARCH_ITERATION_CROSS_EXPERIMENT_PARENT",
        }:
            raise
        raise OnlySearchProvenanceError(
            "SEARCH_ITERATION_PARENT_INVALID",
            plan.parent_iteration_result_fingerprint or plan.experiment_fingerprint,
        ) from exc
    except Exception as exc:
        raise OnlySearchProvenanceError(
            "SEARCH_ITERATION_PARENT_INVALID",
            plan.parent_iteration_result_fingerprint or plan.experiment_fingerprint,
        ) from exc


def verify_search_experiment_references(
    experiment: OnlySearchExperimentManifestV1,
    *,
    catalogs: OnlySearchCatalogGenerationReader,
    datasets: OnlySearchDatasetReader,
) -> None:
    """Verify exact Catalog Generation and Dataset Snapshot bindings."""

    try:
        catalog = catalogs.generation(experiment.catalog_generation_fingerprint)
        if catalog.generation_fingerprint != experiment.catalog_generation_fingerprint:
            raise ValueError("Catalog Generation reader returned a different identity")
    except Exception as exc:
        raise OnlySearchProvenanceError(
            "SEARCH_CATALOG_GENERATION_REFERENCE_INVALID",
            experiment.catalog_generation_fingerprint,
        ) from exc
    try:
        dataset = datasets.load_verified_table(experiment.dataset_snapshot_fingerprint)
        if dataset.snapshot.snapshot_fingerprint != experiment.dataset_snapshot_fingerprint:
            raise ValueError("Dataset reader returned a different identity")
    except Exception as exc:
        raise OnlySearchProvenanceError(
            "SEARCH_DATASET_SNAPSHOT_REFERENCE_INVALID",
            experiment.dataset_snapshot_fingerprint,
        ) from exc


def verify_search_iteration_result_references(
    result: OnlySearchIterationResultV1,
    *,
    expected_dataset_snapshot_fingerprint: str,
    candidates: OnlySearchCandidateReader | None,
    research_results: OnlySearchResearchResultReader | None,
    qualification_decisions: OnlySearchQualificationDecisionReader | None,
) -> None:
    """Verify external exact references without recomputing Research or Qualification."""

    candidate = None
    if result.candidate_fingerprint is not None and candidates is not None:
        try:
            candidate = candidates.load_verified(result.candidate_fingerprint)
            if candidate.candidate_fingerprint != result.candidate_fingerprint:
                raise ValueError("Candidate reader returned a different identity")
        except Exception as exc:
            raise OnlySearchProvenanceError(
                "SEARCH_CANDIDATE_REFERENCE_INVALID",
                result.candidate_fingerprint,
            ) from exc

    research_result = None
    if result.research_result_fingerprint is not None:
        if research_results is None:
            raise OnlySearchProvenanceError(
                "SEARCH_EXTERNAL_REFERENCE_READER_UNAVAILABLE",
                "Research Result reader",
            )
        try:
            research_result = research_results.load_verified(result.research_result_fingerprint)
            if research_result.manifest.research_result_fingerprint != result.research_result_fingerprint:
                raise ValueError("Research Result reader returned a different identity")
            if research_result.manifest.dataset_snapshot_fingerprint != expected_dataset_snapshot_fingerprint:
                raise ValueError("Research Result belongs to a different Dataset Snapshot")
            if result.candidate_fingerprint is not None:
                candidate_fingerprints = {
                    item.candidate_fingerprint for item in research_result.manifest.plan.candidates
                }
                if result.candidate_fingerprint not in candidate_fingerprints:
                    raise ValueError("Research Result does not contain the bound Candidate")
        except OnlySearchProvenanceError:
            raise
        except Exception as exc:
            raise OnlySearchProvenanceError(
                "SEARCH_RESEARCH_RESULT_REFERENCE_INVALID",
                result.research_result_fingerprint,
            ) from exc

    if result.qualification_decision_fingerprint is not None:
        if qualification_decisions is None:
            raise OnlySearchProvenanceError(
                "SEARCH_EXTERNAL_REFERENCE_READER_UNAVAILABLE",
                "Qualification Decision reader",
            )
        try:
            decision = qualification_decisions.load_verified(result.qualification_decision_fingerprint)
            if decision.decision_fingerprint != result.qualification_decision_fingerprint:
                raise ValueError("Qualification Decision reader returned a different identity")
            if result.research_result_fingerprint is not None and all(
                item.evidence_fingerprint != result.research_result_fingerprint for item in decision.evidence
            ):
                raise ValueError("Qualification Decision does not bind the exact Research Result")
        except OnlySearchProvenanceError:
            raise
        except Exception as exc:
            raise OnlySearchProvenanceError(
                "SEARCH_QUALIFICATION_DECISION_REFERENCE_INVALID",
                result.qualification_decision_fingerprint,
            ) from exc


__all__ = [name for name in globals() if name.startswith(("OnlySearch", "verify_search"))]
