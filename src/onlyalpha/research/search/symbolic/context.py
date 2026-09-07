"""Cross-authority resolution for historical and executable symbolic contexts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.quant_assets import OnlyQuantAssetCatalogGeneration
from onlyalpha.research.dataset.ports import OnlyVerifiedResearchDataset
from onlyalpha.research.experiment import OnlySearchExperimentManifestV2, OnlySearchIterationPlanV1
from onlyalpha.research.specification.resolver import (
    OnlyResearchDeferredTemplateResolution,
    OnlyResearchSpecificationResolver,
)

from .algorithm import (
    OnlySymbolicSearchAlgorithmImplementationManifestV1,
    only_deterministic_enumeration_implementation,
)
from .enumeration_result import OnlySymbolicEnumerationResultV1
from .errors import OnlySymbolicSearchError
from .evaluation import (
    SYMBOLIC_EVALUATION_CONTRACT_KIND,
    SYMBOLIC_EVALUATION_CONTRACT_SCHEMA_VERSION,
    OnlySymbolicResearchEvaluationContractV1,
)
from .historical import (
    OnlyVerifiedSymbolicEnumerationResultV1,
    load_symbolic_enumeration_result_historical_verified,
    verify_symbolic_historical_iteration_occurrence,
)
from .model import OnlySymbolicFactorSearchSpaceV2
from .store import OnlyJsonSymbolicSearchStore
from .verification import (
    OnlyVerifiedSymbolicProposalV1,
    OnlyVerifiedSymbolicSearchSpaceV1,
    verify_symbolic_experiment_binding,
    verify_symbolic_search_space,
)


class OnlySymbolicCatalogReader(Protocol):
    def generation(self, fingerprint: str) -> OnlyQuantAssetCatalogGeneration: ...


class OnlySymbolicDatasetReader(Protocol):
    def load_verified_table(self, snapshot_fingerprint: str) -> OnlyVerifiedResearchDataset: ...


@dataclass(frozen=True, slots=True)
class OnlyVerifiedSymbolicEvaluationContextV1:
    evaluation_contract: OnlySymbolicResearchEvaluationContractV1
    fixed_resolution: OnlyResearchDeferredTemplateResolution


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


def verify_symbolic_evaluation_context(
    evaluation: OnlySymbolicResearchEvaluationContractV1,
    verified_search_space: OnlyVerifiedSymbolicSearchSpaceV1,
    research_calculation_registry: OnlyCalculationRegistry,
) -> OnlyVerifiedSymbolicEvaluationContextV1:
    """Close fixed Evaluation semantics without executing a Search Algorithm."""

    try:
        if not isinstance(verified_search_space, OnlyVerifiedSymbolicSearchSpaceV1):
            raise ValueError("Verified Search Space is required")
        resolution = OnlyResearchSpecificationResolver(
            research_calculation_registry
        ).verify_deferred_calculation_template(
            dataset_snapshot_fingerprint=evaluation.dataset_snapshot_fingerprint,
            fixed_calculations=evaluation.fixed_calculations,
            statistics=evaluation.statistics,
            evidence=evaluation.evidence,
            deferred_calculation_id=evaluation.candidate_calculation_id,
        )
    except Exception as exc:
        raise OnlySymbolicSearchError(
            "SEARCH_EVALUATION_CONTEXT_INVALID", evaluation.evaluation_contract_fingerprint
        ) from exc
    fixed_ids = {item.calculation_id for item in evaluation.fixed_calculations}
    if fixed_ids - {item.calculation_id for item in resolution.fixed_candidates}:
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

    def certify_current_runtime_enumeration_reproduction(
        self, experiment: OnlySearchExperimentManifestV2
    ) -> OnlySymbolicEnumerationResultV1:
        """Re-enumerate only after runtime admission and compare with durable output."""

        from .execution import enumerate_symbolic_executable_context

        context = self.resolve_verified_context(experiment)
        executable = self.admit_current_runtime(context)
        _execution, reproduced = enumerate_symbolic_executable_context(executable)
        stored = load_symbolic_enumeration_result_historical_verified(experiment, context, self._symbolic_store).result
        if reproduced != stored:
            raise OnlySymbolicSearchError(
                "SEARCH_ENUMERATION_REPRODUCTION_MISMATCH", stored.enumeration_result_fingerprint
            )
        return reproduced

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
        return verify_symbolic_historical_iteration_occurrence(experiment, plan, context, self._symbolic_store)

    def load_proposal_occurrence_contextual_verified(
        self,
        experiment: OnlySearchExperimentManifestV2,
        plan: OnlySearchIterationPlanV1,
    ) -> OnlyVerifiedSymbolicProposalV1:
        """Compatibility adapter: occurrence is now a durable historical proof."""

        context = self.resolve_verified_context(experiment)
        return verify_symbolic_historical_iteration_occurrence(experiment, plan, context, self._symbolic_store)

    def load_enumeration_result_contextual_verified(
        self, experiment: OnlySearchExperimentManifestV2
    ) -> OnlyVerifiedSymbolicEnumerationResultV1:
        context = self.resolve_verified_context(experiment)
        return load_symbolic_enumeration_result_historical_verified(experiment, context, self._symbolic_store)

    @staticmethod
    def verify_iteration_plan_ledger(
        experiment: OnlySearchExperimentManifestV2,
        plan: OnlySearchIterationPlanV1,
        committed_plans: tuple[OnlySearchIterationPlanV1, ...],
    ) -> None:
        """Require the deterministic symbolic ledger to remain one contiguous prefix."""

        relevant = tuple(
            item for item in committed_plans if item.experiment_fingerprint == experiment.experiment_fingerprint
        )
        by_ordinal: dict[int, OnlySearchIterationPlanV1] = {}
        for existing in relevant:
            occupant = by_ordinal.get(existing.iteration_index)
            if occupant is not None and occupant != existing:
                raise OnlySymbolicSearchError("SEARCH_ITERATION_ORDINAL_CONFLICT", str(existing.iteration_index))
            by_ordinal[existing.iteration_index] = existing
        if set(by_ordinal) != set(range(len(by_ordinal))):
            raise OnlySymbolicSearchError("SEARCH_ITERATION_PREFIX_CORRUPT", experiment.experiment_fingerprint)
        occupant = by_ordinal.get(plan.iteration_index)
        if occupant is not None:
            if occupant != plan:
                raise OnlySymbolicSearchError("SEARCH_ITERATION_ORDINAL_CONFLICT", str(plan.iteration_index))
            return
        if plan.iteration_index != len(by_ordinal):
            raise OnlySymbolicSearchError("SEARCH_ITERATION_PREFIX_GAP", str(plan.iteration_index))

    @staticmethod
    def next_iteration_ordinal(
        experiment: OnlySearchExperimentManifestV2,
        committed_plans: tuple[OnlySearchIterationPlanV1, ...],
    ) -> int:
        relevant = tuple(
            item for item in committed_plans if item.experiment_fingerprint == experiment.experiment_fingerprint
        )
        ordinals = {item.iteration_index for item in relevant}
        if len(ordinals) != len(relevant) or ordinals != set(range(len(relevant))):
            raise OnlySymbolicSearchError("SEARCH_ITERATION_PREFIX_CORRUPT", experiment.experiment_fingerprint)
        return len(relevant)


__all__ = [name for name in globals() if name.startswith(("Only", "admit_", "verify_"))]
