"""Exact Search Experiment lineage and external-reference verification ports."""

from __future__ import annotations

from typing import Protocol

from .errors import OnlySearchProvenanceError
from .model import (
    OnlySearchExperimentManifest,
    OnlySearchExperimentManifestV2,
    OnlySearchIterationPlanV1,
    OnlySearchIterationResultV1,
)


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


class OnlySearchSpaceValue(Protocol):
    @property
    def schema_version(self) -> int: ...

    @property
    def search_space_fingerprint(self) -> str: ...

    @property
    def catalog_generation_fingerprint(self) -> str: ...


class OnlySearchSpaceReader(Protocol):
    def load_search_space_verified(self, fingerprint: str) -> OnlySearchSpaceValue: ...


class OnlySearchProposalValue(Protocol):
    @property
    def schema_version(self) -> int: ...

    @property
    def proposal_fingerprint(self) -> str: ...

    @property
    def search_space_fingerprint(self) -> str: ...


class OnlySearchProposalReader(Protocol):
    def load_proposal_verified(self, fingerprint: str) -> OnlySearchProposalValue: ...


class OnlySearchContextValue(Protocol):
    @property
    def experiment(self) -> OnlySearchExperimentManifestV2: ...


class OnlySearchContextReader(Protocol):
    def resolve_verified_context(self, experiment: OnlySearchExperimentManifestV2) -> OnlySearchContextValue: ...

    def load_proposal_contextual_verified(
        self, experiment: OnlySearchExperimentManifestV2, plan: OnlySearchIterationPlanV1
    ) -> object: ...


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
    def research_result_plan_fingerprint(self) -> str: ...

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
    def load_verified(self, research_result_locator_fingerprint: str) -> OnlySearchResearchResultValue: ...


class OnlySearchQualificationEvidenceValue(Protocol):
    @property
    def kind(self) -> object: ...

    @property
    def evidence_fingerprint(self) -> str: ...

    @property
    def locator_fingerprint(self) -> str | None: ...

    @property
    def subject_binding_fingerprint(self) -> str | None: ...


class OnlySearchQualificationDecisionValue(Protocol):
    @property
    def decision_fingerprint(self) -> str: ...

    @property
    def evidence(self) -> tuple[OnlySearchQualificationEvidenceValue, ...]: ...

    @property
    def subject_strategy_fingerprint(self) -> str: ...


class OnlySearchQualificationDecisionReader(Protocol):
    def load_verified(self, decision_fingerprint: str) -> OnlySearchQualificationDecisionValue: ...


class OnlySearchFreezeRelationValue(Protocol):
    @property
    def relation_fingerprint(self) -> str: ...

    @property
    def candidate_fingerprint(self) -> str: ...

    @property
    def research_result_fingerprint(self) -> str: ...

    @property
    def strategy_fingerprint(self) -> str: ...


class OnlySearchFreezeRelationReader(Protocol):
    def load_freeze_relation(self, relation_fingerprint: str) -> OnlySearchFreezeRelationValue: ...


class OnlySearchExperimentReader(Protocol):
    def load_experiment_verified(self, experiment_fingerprint: str) -> OnlySearchExperimentManifest: ...


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
    experiment: OnlySearchExperimentManifest,
    *,
    catalogs: OnlySearchCatalogGenerationReader,
    datasets: OnlySearchDatasetReader,
    search_spaces: OnlySearchSpaceReader | None = None,
    search_contexts: OnlySearchContextReader | None = None,
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
    reference = experiment.search_space_reference
    if reference.search_space_kind == "ONLY_SYMBOLIC_FACTOR_SEARCH_SPACE":
        if isinstance(experiment, OnlySearchExperimentManifestV2):
            if search_contexts is None:
                raise OnlySearchProvenanceError(
                    "SEARCH_EXTERNAL_REFERENCE_READER_UNAVAILABLE",
                    "Verified Symbolic Search Context reader",
                )
            try:
                context = search_contexts.resolve_verified_context(experiment)
                if context.experiment.experiment_fingerprint != experiment.experiment_fingerprint:
                    raise ValueError("Verified Search Context belongs to a different Experiment")
            except OnlySearchProvenanceError:
                raise
            except Exception as exc:
                raise OnlySearchProvenanceError(
                    "SEARCH_CONTEXT_REFERENCE_INVALID",
                    experiment.experiment_fingerprint,
                ) from exc
            return
        if search_spaces is None:
            raise OnlySearchProvenanceError(
                "SEARCH_EXTERNAL_REFERENCE_READER_UNAVAILABLE",
                "Symbolic Search Space reader",
            )
        try:
            value = search_spaces.load_search_space_verified(reference.search_space_fingerprint)
            if (
                value.schema_version != reference.search_space_schema_version
                or value.search_space_fingerprint != reference.search_space_fingerprint
                or value.catalog_generation_fingerprint != experiment.catalog_generation_fingerprint
            ):
                raise ValueError("Symbolic Search Space reader returned a different identity")
        except OnlySearchProvenanceError:
            raise
        except Exception as exc:
            raise OnlySearchProvenanceError(
                "SEARCH_SPACE_REFERENCE_INVALID",
                reference.search_space_fingerprint,
            ) from exc


def verify_search_iteration_proposal_reference(
    plan: OnlySearchIterationPlanV1,
    *,
    experiment: OnlySearchExperimentManifest,
    proposals: OnlySearchProposalReader | None,
    search_contexts: OnlySearchContextReader | None,
    expected_search_space_fingerprint: str,
) -> None:
    """Close method-specific Proposal references once their Authority exists."""

    if plan.proposal_kind != "ONLY_SYMBOLIC_GRAPH_PROPOSAL":
        return
    if isinstance(experiment, OnlySearchExperimentManifestV2):
        if search_contexts is None:
            raise OnlySearchProvenanceError(
                "SEARCH_EXTERNAL_REFERENCE_READER_UNAVAILABLE",
                "Verified Symbolic Proposal reader",
            )
        try:
            search_contexts.load_proposal_contextual_verified(experiment, plan)
        except Exception as exc:
            raise OnlySearchProvenanceError("SEARCH_PROPOSAL_REFERENCE_INVALID", plan.proposal_fingerprint) from exc
        return
    if proposals is None:
        raise OnlySearchProvenanceError(
            "SEARCH_EXTERNAL_REFERENCE_READER_UNAVAILABLE",
            "Symbolic Proposal reader",
        )
    try:
        proposal = proposals.load_proposal_verified(plan.proposal_fingerprint)
        if (
            proposal.schema_version != plan.proposal_schema_version
            or proposal.proposal_fingerprint != plan.proposal_fingerprint
            or proposal.search_space_fingerprint != expected_search_space_fingerprint
        ):
            raise ValueError("Symbolic Proposal reader returned a different identity")
    except OnlySearchProvenanceError:
        raise
    except Exception as exc:
        raise OnlySearchProvenanceError(
            "SEARCH_PROPOSAL_REFERENCE_INVALID",
            plan.proposal_fingerprint,
        ) from exc


def verify_search_iteration_result_references(
    result: OnlySearchIterationResultV1,
    *,
    expected_dataset_snapshot_fingerprint: str,
    candidates: OnlySearchCandidateReader | None,
    research_results: OnlySearchResearchResultReader | None,
    qualification_decisions: OnlySearchQualificationDecisionReader | None,
    freeze_relations: OnlySearchFreezeRelationReader | None,
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

    research_reference = result.research_result_reference
    if research_reference is not None:
        if research_results is None:
            raise OnlySearchProvenanceError(
                "SEARCH_EXTERNAL_REFERENCE_READER_UNAVAILABLE",
                "Research Result reader",
            )
        try:
            research_result = research_results.load_verified(research_reference.locator_fingerprint)
            if research_result.manifest.research_result_plan_fingerprint != research_reference.locator_fingerprint:
                raise ValueError("Research Result reader returned a different locator")
            if research_result.manifest.research_result_fingerprint != research_reference.result_fingerprint:
                raise ValueError("Research Result reader returned a different identity")
        except Exception as exc:
            raise OnlySearchProvenanceError(
                "SEARCH_RESEARCH_RESULT_REFERENCE_INVALID",
                research_reference.locator_fingerprint,
            ) from exc
        try:
            if research_result.manifest.dataset_snapshot_fingerprint != expected_dataset_snapshot_fingerprint:
                raise ValueError("Research Result belongs to a different Dataset Snapshot")
            if result.candidate_fingerprint is not None:
                candidate_fingerprints = tuple(
                    item.candidate_fingerprint for item in research_result.manifest.plan.candidates
                )
                if candidate_fingerprints.count(result.candidate_fingerprint) != 1:
                    raise ValueError("Research Result Candidate membership is not exact and unique")
        except Exception as exc:
            raise OnlySearchProvenanceError(
                "SEARCH_RESEARCH_RESULT_SUBJECT_MISMATCH",
                research_reference.result_fingerprint,
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
        except Exception as exc:
            raise OnlySearchProvenanceError(
                "SEARCH_QUALIFICATION_DECISION_REFERENCE_INVALID",
                result.qualification_decision_fingerprint,
            ) from exc
        if research_reference is None or result.candidate_fingerprint is None:
            raise OnlySearchProvenanceError(
                "SEARCH_QUALIFICATION_DECISION_REFERENCE_INVALID",
                result.qualification_decision_fingerprint,
            )
        if freeze_relations is None:
            raise OnlySearchProvenanceError(
                "SEARCH_EXTERNAL_REFERENCE_READER_UNAVAILABLE",
                "Freeze Relation reader",
            )
        try:
            matches = tuple(
                item
                for item in decision.evidence
                if _evidence_kind(item.kind) == "RESEARCH_RESULT"
                and item.evidence_fingerprint == research_reference.result_fingerprint
                and item.locator_fingerprint == research_reference.locator_fingerprint
            )
            if len(matches) != 1:
                raise ValueError("Qualification Decision must contain exactly one matching Research Evidence")
            subject_binding = matches[0].subject_binding_fingerprint
            if subject_binding is None:
                raise ValueError("Qualification Research Evidence requires an exact Freeze relation")
            relation = freeze_relations.load_freeze_relation(subject_binding)
            if relation.relation_fingerprint != subject_binding:
                raise ValueError("Freeze Relation reader returned a different identity")
        except Exception as exc:
            raise OnlySearchProvenanceError(
                "SEARCH_QUALIFICATION_DECISION_REFERENCE_INVALID",
                result.qualification_decision_fingerprint,
            ) from exc
        if (
            relation.candidate_fingerprint != result.candidate_fingerprint
            or relation.research_result_fingerprint != research_reference.result_fingerprint
            or relation.strategy_fingerprint != decision.subject_strategy_fingerprint
        ):
            raise OnlySearchProvenanceError(
                "SEARCH_QUALIFICATION_DECISION_SUBJECT_MISMATCH",
                result.qualification_decision_fingerprint,
            )


def _evidence_kind(value: object) -> object:
    """Normalize string enums without importing the Qualification producer contract."""

    return getattr(value, "value", value)


__all__ = [name for name in globals() if name.startswith(("OnlySearch", "verify_search"))]
