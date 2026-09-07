"""Cross-authority resolution for a complete symbolic Search context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.quant_assets import OnlyQuantAssetCatalogGeneration
from onlyalpha.research.dataset.ports import OnlyVerifiedResearchDataset
from onlyalpha.research.experiment import OnlySearchExperimentManifestV2, OnlySearchIterationPlanV1

from .algorithm import (
    OnlySymbolicSearchAlgorithmImplementationV1,
    only_deterministic_enumeration_implementation,
)
from .errors import OnlySymbolicSearchError
from .evaluation import (
    SYMBOLIC_EVALUATION_CONTRACT_KIND,
    SYMBOLIC_EVALUATION_CONTRACT_SCHEMA_VERSION,
    OnlySymbolicResearchEvaluationContractV1,
)
from .model import (
    OnlySymbolicFactorSearchSpaceV2,
)
from .store import OnlyJsonSymbolicSearchStore
from .verification import (
    OnlyVerifiedSymbolicProposalV1,
    OnlyVerifiedSymbolicSearchSpaceV1,
    verify_symbolic_experiment_binding,
    verify_symbolic_iteration_proposal_binding,
    verify_symbolic_proposal_reconstruction,
    verify_symbolic_search_space,
)


class OnlySymbolicCatalogReader(Protocol):
    def generation(self, fingerprint: str) -> OnlyQuantAssetCatalogGeneration: ...


class OnlySymbolicDatasetReader(Protocol):
    def load_verified_table(self, snapshot_fingerprint: str) -> OnlyVerifiedResearchDataset: ...


@dataclass(frozen=True, slots=True)
class OnlyVerifiedSymbolicSearchContextV1:
    experiment: OnlySearchExperimentManifestV2
    verified_search_space: OnlyVerifiedSymbolicSearchSpaceV1
    evaluation_contract: OnlySymbolicResearchEvaluationContractV1
    catalog_generation: OnlyQuantAssetCatalogGeneration
    verified_dataset: OnlyVerifiedResearchDataset
    algorithm_implementation: OnlySymbolicSearchAlgorithmImplementationV1


class OnlySymbolicSearchContextResolver:
    """Resolve exact external Authorities before any symbolic execution."""

    def __init__(
        self,
        *,
        symbolic_store: OnlyJsonSymbolicSearchStore,
        catalogs: OnlySymbolicCatalogReader,
        datasets: OnlySymbolicDatasetReader,
        algorithm_implementation: OnlySymbolicSearchAlgorithmImplementationV1 | None = None,
    ) -> None:
        self._symbolic_store = symbolic_store
        self._catalogs = catalogs
        self._datasets = datasets
        self._algorithm = algorithm_implementation or only_deterministic_enumeration_implementation()

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
        actual = self._algorithm
        if (
            binding.algorithm_id != actual.algorithm_id
            or binding.algorithm_semantic_version != actual.algorithm_semantic_version
            or binding.implementation_fingerprint != actual.implementation_fingerprint
            or binding.source_revision != actual.source_revision
        ):
            raise OnlySymbolicSearchError("SEARCH_ALGORITHM_IMPLEMENTATION_MISMATCH", binding.algorithm_id)
        verified_space = verify_symbolic_search_space(space_value, catalog, dataset)
        return OnlyVerifiedSymbolicSearchContextV1(
            experiment,
            verified_space,
            evaluation,
            catalog,
            dataset,
            actual,
        )

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
        verify_symbolic_iteration_proposal_binding(
            plan,
            proposal,
            expected_search_space_fingerprint=context.verified_search_space.search_space.search_space_fingerprint,
        )
        return verify_symbolic_proposal_reconstruction(proposal, context)


__all__ = [name for name in globals() if name.startswith("OnlySymbolic")]
