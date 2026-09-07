"""Cross-authority resolution for historical and executable symbolic contexts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.quant_assets import OnlyQuantAssetCatalogGeneration
from onlyalpha.research.dataset.ports import OnlyVerifiedResearchDataset
from onlyalpha.research.experiment import OnlySearchExperimentManifestV2, OnlySearchIterationPlanV1
from onlyalpha.research.specification.resolver import (
    OnlyResearchSpecificationResolution,
    OnlyResearchSpecificationResolver,
)

from .algorithm import (
    OnlySymbolicSearchAlgorithmImplementationManifestV1,
    only_deterministic_enumeration_implementation,
)
from .enumeration import enumerate_symbolic_factor_proposals
from .errors import OnlySymbolicSearchError
from .evaluation import (
    SYMBOLIC_EVALUATION_CONTRACT_KIND,
    SYMBOLIC_EVALUATION_CONTRACT_SCHEMA_VERSION,
    OnlySymbolicResearchEvaluationContractV1,
)
from .materialization import materialize_symbolic_research_specification
from .model import OnlySymbolicFactorSearchSpaceV2
from .store import OnlyJsonSymbolicSearchStore
from .verification import (
    OnlyVerifiedSymbolicProposalV1,
    OnlyVerifiedSymbolicSearchSpaceV1,
    verify_symbolic_experiment_binding,
    verify_symbolic_iteration_historical_binding,
    verify_symbolic_iteration_occurrence,
    verify_symbolic_proposal_reconstruction,
    verify_symbolic_search_space,
)


class OnlySymbolicCatalogReader(Protocol):
    def generation(self, fingerprint: str) -> OnlyQuantAssetCatalogGeneration: ...


class OnlySymbolicDatasetReader(Protocol):
    def load_verified_table(self, snapshot_fingerprint: str) -> OnlyVerifiedResearchDataset: ...


@dataclass(frozen=True, slots=True)
class OnlyVerifiedSymbolicEvaluationContextV1:
    evaluation_contract: OnlySymbolicResearchEvaluationContractV1
    witness_resolution: OnlyResearchSpecificationResolution


@dataclass(frozen=True, slots=True)
class OnlyVerifiedSymbolicSearchContextV1:
    experiment: OnlySearchExperimentManifestV2
    verified_search_space: OnlyVerifiedSymbolicSearchSpaceV1
    verified_evaluation: OnlyVerifiedSymbolicEvaluationContextV1
    catalog_generation: OnlyQuantAssetCatalogGeneration
    verified_dataset: OnlyVerifiedResearchDataset
    historical_algorithm_manifest: OnlySymbolicSearchAlgorithmImplementationManifestV1

    @property
    def evaluation_contract(self) -> OnlySymbolicResearchEvaluationContractV1:
        return self.verified_evaluation.evaluation_contract

    @property
    def algorithm_implementation(self) -> OnlySymbolicSearchAlgorithmImplementationManifestV1:
        """Compatibility projection; historical Manifest is the authoritative value."""

        return self.historical_algorithm_manifest


@dataclass(frozen=True, slots=True)
class OnlyExecutableSymbolicSearchContextV1:
    historical_context: OnlyVerifiedSymbolicSearchContextV1
    runtime_algorithm_manifest: OnlySymbolicSearchAlgorithmImplementationManifestV1


@dataclass(frozen=True, slots=True)
class _EvaluationWitnessContext:
    verified_search_space: OnlyVerifiedSymbolicSearchSpaceV1
    evaluation_contract: OnlySymbolicResearchEvaluationContractV1


def verify_symbolic_evaluation_context(
    evaluation: OnlySymbolicResearchEvaluationContractV1,
    verified_search_space: OnlyVerifiedSymbolicSearchSpaceV1,
    research_calculation_registry: OnlyCalculationRegistry,
) -> OnlyVerifiedSymbolicEvaluationContextV1:
    """Close fixed Evaluation semantics through the normal Research resolver."""

    try:
        enumeration = enumerate_symbolic_factor_proposals(verified_search_space, proposal_limit=1)
        if not enumeration.proposals:
            raise ValueError("Search Space has no admitted Candidate witness")
        witness_context = _EvaluationWitnessContext(verified_search_space, evaluation)
        verified_proposal = verify_symbolic_proposal_reconstruction(enumeration.proposals[0], witness_context)
        specification = materialize_symbolic_research_specification(evaluation, verified_proposal).specification
        resolution = OnlyResearchSpecificationResolver(research_calculation_registry).resolve(specification)
    except Exception as exc:
        raise OnlySymbolicSearchError(
            "SEARCH_EVALUATION_CONTEXT_INVALID", evaluation.evaluation_contract_fingerprint
        ) from exc
    candidate = tuple(
        item for item in resolution.candidates if item.calculation_id == evaluation.candidate_calculation_id
    )
    fixed_ids = {item.calculation_id for item in evaluation.fixed_calculations}
    if len(candidate) != 1 or fixed_ids - {item.calculation_id for item in resolution.candidates}:
        raise OnlySymbolicSearchError("SEARCH_EVALUATION_CONTEXT_INVALID", evaluation.evaluation_contract_fingerprint)
    return OnlyVerifiedSymbolicEvaluationContextV1(evaluation, resolution)


def admit_current_symbolic_algorithm_runtime(
    context: OnlyVerifiedSymbolicSearchContextV1,
    runtime_manifest: OnlySymbolicSearchAlgorithmImplementationManifestV1 | None = None,
) -> OnlyExecutableSymbolicSearchContextV1:
    """Admit execution only when current code is the exact historical implementation."""

    actual = runtime_manifest or only_deterministic_enumeration_implementation()
    historical = context.historical_algorithm_manifest
    if actual.to_dict() != historical.to_dict():
        raise OnlySymbolicSearchError("SEARCH_ALGORITHM_RUNTIME_MISMATCH", historical.implementation_fingerprint)
    return OnlyExecutableSymbolicSearchContextV1(context, actual)


class OnlySymbolicSearchContextResolver:
    """Resolve historical Authorities without conflating current runtime admission."""

    def __init__(
        self,
        *,
        symbolic_store: OnlyJsonSymbolicSearchStore,
        catalogs: OnlySymbolicCatalogReader,
        datasets: OnlySymbolicDatasetReader,
        research_calculation_registry: OnlyCalculationRegistry | None = None,
        algorithm_implementation: OnlySymbolicSearchAlgorithmImplementationManifestV1 | None = None,
    ) -> None:
        self._symbolic_store = symbolic_store
        self._catalogs = catalogs
        self._datasets = datasets
        self._research_registry = research_calculation_registry
        self._runtime_algorithm = algorithm_implementation

    def resolve_verified_context(
        self, experiment: OnlySearchExperimentManifestV2
    ) -> OnlyVerifiedSymbolicSearchContextV1:
        if not isinstance(experiment, OnlySearchExperimentManifestV2):
            raise OnlySymbolicSearchError("SEARCH_EXPERIMENT_SCHEMA_UNSUPPORTED", "B3.2 requires Experiment V2")
        try:
            catalog = self._catalogs.generation(experiment.catalog_generation_fingerprint)
            if catalog.generation_fingerprint != experiment.catalog_generation_fingerprint:
                raise ValueError("Catalog identity differs")
        except Exception as exc:
            raise OnlySymbolicSearchError(
                "SEARCH_CATALOG_REFERENCE_INVALID", experiment.catalog_generation_fingerprint
            ) from exc
        try:
            dataset = self._datasets.load_verified_table(experiment.dataset_snapshot_fingerprint)
            if dataset.snapshot.snapshot_fingerprint != experiment.dataset_snapshot_fingerprint:
                raise ValueError("Dataset identity differs")
        except Exception as exc:
            raise OnlySymbolicSearchError(
                "SEARCH_DATASET_REFERENCE_INVALID", experiment.dataset_snapshot_fingerprint
            ) from exc
        space_value = self._symbolic_store.load_search_space_intrinsic_verified(
            experiment.search_space_reference.search_space_fingerprint
        )
        if not isinstance(space_value, OnlySymbolicFactorSearchSpaceV2):
            raise OnlySymbolicSearchError("SEARCH_SPACE_SCHEMA_UNSUPPORTED", "B3.2 requires Search Space V2")
        evaluation = self._symbolic_store.load_evaluation_contract_intrinsic_verified(
            experiment.evaluation_context_reference.evaluation_fingerprint
        )
        evaluation_reference = experiment.evaluation_context_reference
        if (
            evaluation_reference.evaluation_kind != SYMBOLIC_EVALUATION_CONTRACT_KIND
            or evaluation_reference.evaluation_schema_version != SYMBOLIC_EVALUATION_CONTRACT_SCHEMA_VERSION
            or evaluation_reference.evaluation_fingerprint != evaluation.evaluation_contract_fingerprint
        ):
            raise OnlySymbolicSearchError(
                "SEARCH_EVALUATION_REFERENCE_INVALID", evaluation_reference.evaluation_fingerprint
            )
        if evaluation.dataset_snapshot_fingerprint != experiment.dataset_snapshot_fingerprint:
            raise OnlySymbolicSearchError(
                "SEARCH_EVALUATION_DATASET_MISMATCH", evaluation.evaluation_contract_fingerprint
            )
        verify_symbolic_experiment_binding(experiment, space_value)
        binding = experiment.search_algorithm_binding
        try:
            historical = self._symbolic_store.load_algorithm_implementation_manifest_intrinsic_verified(
                binding.implementation_fingerprint
            )
        except Exception as exc:
            raise OnlySymbolicSearchError(
                "SEARCH_ALGORITHM_MANIFEST_REFERENCE_INVALID", binding.implementation_fingerprint
            ) from exc
        if (
            binding.algorithm_id != historical.algorithm_id
            or binding.algorithm_semantic_version != historical.algorithm_semantic_version
            or binding.implementation_fingerprint != historical.implementation_fingerprint
            or binding.source_revision != historical.source_revision
        ):
            raise OnlySymbolicSearchError("SEARCH_ALGORITHM_MANIFEST_REFERENCE_INVALID", binding.algorithm_id)
        verified_space = verify_symbolic_search_space(space_value, catalog, dataset)
        research_registry = self._research_registry or verified_space.calculation_registry
        verified_evaluation = verify_symbolic_evaluation_context(evaluation, verified_space, research_registry)
        return OnlyVerifiedSymbolicSearchContextV1(
            experiment,
            verified_space,
            verified_evaluation,
            catalog,
            dataset,
            historical,
        )

    def admit_current_runtime(
        self, context: OnlyVerifiedSymbolicSearchContextV1
    ) -> OnlyExecutableSymbolicSearchContextV1:
        return admit_current_symbolic_algorithm_runtime(context, self._runtime_algorithm)

    def load_search_space_contextual_verified(
        self, experiment: OnlySearchExperimentManifestV2
    ) -> OnlySymbolicFactorSearchSpaceV2:
        return self.resolve_verified_context(experiment).verified_search_space.search_space

    def load_proposal_contextual_verified(
        self,
        experiment: OnlySearchExperimentManifestV2,
        plan: OnlySearchIterationPlanV1,
    ) -> OnlyVerifiedSymbolicProposalV1:
        context = self.resolve_verified_context(experiment)
        proposal = self._symbolic_store.load_proposal_intrinsic_verified(plan.proposal_fingerprint)
        return verify_symbolic_iteration_historical_binding(experiment, plan, proposal, context)

    def load_proposal_occurrence_contextual_verified(
        self,
        experiment: OnlySearchExperimentManifestV2,
        plan: OnlySearchIterationPlanV1,
    ) -> OnlyVerifiedSymbolicProposalV1:
        context = self.resolve_verified_context(experiment)
        self.admit_current_runtime(context)
        proposal = self._symbolic_store.load_proposal_intrinsic_verified(plan.proposal_fingerprint)
        return verify_symbolic_iteration_occurrence(experiment, plan, proposal, context)


__all__ = [name for name in globals() if name.startswith(("Only", "admit_", "verify_"))]
