"""Cross-authority closure for adaptive parameter Search V1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.calculation.definition import (
    FACTOR_SCORE_SEMANTIC_TYPE,
    FACTOR_VALUE_SEMANTIC_TYPE,
    OnlyCalculationBackendKind,
    OnlyCalculationKind,
)
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.quant_assets import OnlyQuantAssetCatalogGeneration, OnlyQuantAssetLayer
from onlyalpha.research.dataset.ports import OnlyVerifiedResearchDataset
from onlyalpha.research.experiment import (
    OnlySearchDecisionMode,
    OnlySearchExperimentManifestV3,
    OnlySearchIterationPlanV1,
    OnlySearchRandomnessMode,
)
from onlyalpha.research.search.symbolic.evaluation import (
    SYMBOLIC_EVALUATION_CONTRACT_KIND,
    OnlySymbolicResearchEvaluationContractV1,
)
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver

from .errors import OnlyParameterSearchError
from .model import (
    DETERMINISTIC_COARSE_TO_FINE_ALGORITHM_ID,
    DETERMINISTIC_COARSE_TO_FINE_ALGORITHM_SEMANTIC_VERSION,
    PARAMETER_PROPOSAL_KIND,
    PARAMETER_PROPOSAL_SCHEMA_VERSION,
    PARAMETER_SEARCH_POLICY_KIND,
    PARAMETER_SEARCH_SPACE_KIND,
    OnlyParameterFactorSearchSpaceV1,
    OnlyParameterGraphProposalV1,
    OnlyParameterSearchAlgorithmManifestV1,
    OnlyParameterSearchPolicyV1,
    materialize_parameter_proposals,
)
from .store import OnlyJsonParameterSearchStore


class OnlyParameterCatalogReader(Protocol):
    def generation(self, fingerprint: str) -> OnlyQuantAssetCatalogGeneration: ...


class OnlyParameterDatasetReader(Protocol):
    def load_verified_table(self, snapshot_fingerprint: str) -> OnlyVerifiedResearchDataset: ...


class OnlyParameterEvaluationReader(Protocol):
    def load_evaluation_contract_intrinsic_verified(
        self, fingerprint: str
    ) -> OnlySymbolicResearchEvaluationContractV1: ...


@dataclass(frozen=True, slots=True)
class OnlyVerifiedParameterSearchContextV1:
    experiment: OnlySearchExperimentManifestV3
    search_space: OnlyParameterFactorSearchSpaceV1
    policy: OnlyParameterSearchPolicyV1
    evaluation_contract: OnlySymbolicResearchEvaluationContractV1
    catalog_generation: OnlyQuantAssetCatalogGeneration
    verified_dataset: OnlyVerifiedResearchDataset
    historical_algorithm_manifest: OnlyParameterSearchAlgorithmManifestV1
    proposals: tuple[OnlyParameterGraphProposalV1, ...]
    calculation_registry: OnlyCalculationRegistry


class OnlyParameterSearchContextResolver:
    def __init__(
        self,
        *,
        parameter_store: OnlyJsonParameterSearchStore,
        evaluations: OnlyParameterEvaluationReader,
        catalogs: OnlyParameterCatalogReader,
        datasets: OnlyParameterDatasetReader,
    ) -> None:
        self._store = parameter_store
        self._evaluations = evaluations
        self._catalogs = catalogs
        self._datasets = datasets

    def resolve_verified_context(
        self, experiment: OnlySearchExperimentManifestV3
    ) -> OnlyVerifiedParameterSearchContextV1:
        if not isinstance(experiment, OnlySearchExperimentManifestV3):
            raise OnlyParameterSearchError("SEARCH_EXPERIMENT_SCHEMA_UNSUPPORTED", "B3.3 requires V3")
        space = self._store.load_search_space_intrinsic_verified(
            experiment.search_space_reference.search_space_fingerprint
        )
        policy = self._store.load_policy_intrinsic_verified(experiment.search_policy_reference.policy_fingerprint)
        historical = self._store.load_algorithm_manifest_intrinsic_verified(
            experiment.search_algorithm_binding.implementation_fingerprint
        )
        evaluation = self._evaluations.load_evaluation_contract_intrinsic_verified(
            experiment.evaluation_context_reference.evaluation_fingerprint
        )
        catalog = self._catalogs.generation(experiment.catalog_generation_fingerprint)
        dataset = self._datasets.load_verified_table(experiment.dataset_snapshot_fingerprint)
        self._verify_bindings(experiment, space, policy, historical, evaluation, catalog, dataset)
        registry = catalog.calculation_registry()
        self._verify_candidate_authority(space, catalog, registry)
        try:
            OnlyResearchSpecificationResolver(registry).verify_deferred_calculation_template(
                dataset_snapshot_fingerprint=evaluation.dataset_snapshot_fingerprint,
                fixed_calculations=evaluation.fixed_calculations,
                statistics=evaluation.statistics,
                evidence=evaluation.evidence,
                deferred_calculation_id=evaluation.candidate_calculation_id,
            )
        except Exception as exc:
            raise OnlyParameterSearchError(
                "SEARCH_EVALUATION_CONTEXT_INVALID",
                evaluation.evaluation_contract_fingerprint,
            ) from exc
        proposals = materialize_parameter_proposals(space, registry)
        for proposal in proposals:
            stored = self._store.load_proposal_intrinsic_verified(proposal.proposal_fingerprint)
            if stored != proposal:
                raise OnlyParameterSearchError("IDENTITY_MISMATCH", proposal.proposal_fingerprint)
        return OnlyVerifiedParameterSearchContextV1(
            experiment, space, policy, evaluation, catalog, dataset, historical, proposals, registry
        )

    def load_proposal_contextual_verified(
        self,
        experiment: OnlySearchExperimentManifestV3,
        plan: OnlySearchIterationPlanV1,
    ) -> OnlyParameterGraphProposalV1:
        context = self.resolve_verified_context(experiment)
        proposal = self._store.load_proposal_intrinsic_verified(plan.proposal_fingerprint)
        self._verify_occurrence(context, plan, proposal)
        return proposal

    def load_proposal_occurrence_contextual_verified(
        self,
        experiment: OnlySearchExperimentManifestV3,
        plan: OnlySearchIterationPlanV1,
    ) -> OnlyParameterGraphProposalV1:
        return self.load_proposal_contextual_verified(experiment, plan)

    def verify_iteration_plan_ledger(
        self,
        experiment: OnlySearchExperimentManifestV3,
        plan: OnlySearchIterationPlanV1,
        committed_plans: tuple[OnlySearchIterationPlanV1, ...],
    ) -> None:
        context = self.resolve_verified_context(experiment)
        proposal = self._store.load_proposal_intrinsic_verified(plan.proposal_fingerprint)
        self._verify_occurrence(context, plan, proposal)
        merged = {item.iteration_plan_fingerprint: item for item in (*committed_plans, plan)}
        ordered = tuple(sorted(merged.values(), key=lambda item: item.iteration_index))
        if tuple(item.iteration_index for item in ordered) != tuple(range(len(ordered))):
            raise OnlyParameterSearchError("SEARCH_ITERATION_PREFIX_CORRUPT", experiment.experiment_fingerprint)
        if len({item.proposal_fingerprint for item in ordered}) != len(ordered):
            raise OnlyParameterSearchError("SEARCH_ITERATION_PROPOSAL_DUPLICATE", experiment.experiment_fingerprint)

    def next_iteration_ordinal(
        self,
        experiment: OnlySearchExperimentManifestV3,
        committed_plans: tuple[OnlySearchIterationPlanV1, ...],
    ) -> int:
        if not committed_plans:
            return 0
        for plan in committed_plans:
            proposal = self._store.load_proposal_intrinsic_verified(plan.proposal_fingerprint)
            self._verify_occurrence(self.resolve_verified_context(experiment), plan, proposal)
        indices = tuple(sorted(item.iteration_index for item in committed_plans))
        if indices != tuple(range(len(indices))):
            raise OnlyParameterSearchError("SEARCH_ITERATION_PREFIX_CORRUPT", experiment.experiment_fingerprint)
        return len(indices)

    def _verify_occurrence(
        self,
        context: OnlyVerifiedParameterSearchContextV1,
        plan: OnlySearchIterationPlanV1,
        proposal: OnlyParameterGraphProposalV1,
    ) -> None:
        decision = self._store.load_feedback_decision_intrinsic_verified(plan.decision_output_fingerprint)
        try:
            position = decision.ordered_next_proposal_fingerprints.index(proposal.proposal_fingerprint)
        except ValueError as exc:
            raise OnlyParameterSearchError("SEARCH_INVALID_PROPOSAL", plan.proposal_fingerprint) from exc
        if (
            plan.experiment_fingerprint != context.experiment.experiment_fingerprint
            or plan.proposal_kind != PARAMETER_PROPOSAL_KIND
            or plan.proposal_schema_version != PARAMETER_PROPOSAL_SCHEMA_VERSION
            or proposal.search_space_fingerprint != context.search_space.search_space_fingerprint
            or decision.experiment_fingerprint != context.experiment.experiment_fingerprint
            or decision.search_policy_fingerprint != context.policy.policy_fingerprint
            or decision.algorithm_implementation_fingerprint
            != context.historical_algorithm_manifest.implementation_fingerprint
            or plan.iteration_index != decision.start_iteration_index + position
            or plan.decision_input_context_fingerprints != decision.ordered_input_iteration_result_fingerprints
            or plan.decision_tool_result_fingerprints
            or plan.parent_iteration_result_fingerprint != decision.selected_anchor_iteration_result_fingerprint
        ):
            raise OnlyParameterSearchError("SEARCH_INVALID_PROPOSAL", plan.proposal_fingerprint)

    @staticmethod
    def _verify_candidate_authority(
        space: OnlyParameterFactorSearchSpaceV1,
        catalog: OnlyQuantAssetCatalogGeneration,
        registry: OnlyCalculationRegistry,
    ) -> None:
        providers = {
            (
                registration.type_definition.kind,
                registration.type_definition.type_id,
                registration.type_definition.semantic_version,
            ): provider
            for provider in catalog.providers
            for registration in provider.calculation_registrations
        }
        candidate_count = 0
        for node in space.sweep_definition.graph_template.nodes:
            definition = registry.resolve_type(node.type_reference)
            provider = providers.get((definition.kind, definition.type_id, definition.semantic_version))
            if provider is None:
                raise OnlyParameterSearchError("SEARCH_COMPONENT_NOT_IN_CATALOG", definition.type_id)
            registry.resolve(
                definition.kind,
                definition.type_id,
                definition.semantic_version,
                OnlyCalculationBackendKind.RESEARCH,
            )
            if node.template_node_id == space.candidate_template_node_id:
                candidate_count += 1
                output = next(
                    (item for item in definition.outputs if item.name == space.candidate_output_name),
                    None,
                )
                if (
                    provider.manifest.layer is not OnlyQuantAssetLayer.FACTOR
                    or definition.kind is not OnlyCalculationKind.FACTOR
                    or output is None
                    or output.semantic_type not in {FACTOR_VALUE_SEMANTIC_TYPE, FACTOR_SCORE_SEMANTIC_TYPE}
                ):
                    raise OnlyParameterSearchError("SEARCH_CANDIDATE_OUTPUT_INVALID", node.template_node_id)
            elif provider.manifest.layer not in {
                OnlyQuantAssetLayer.OPERATOR,
                OnlyQuantAssetLayer.INDICATOR,
            }:
                raise OnlyParameterSearchError("SEARCH_COMPONENT_LAYER_FORBIDDEN", definition.type_id)
        if candidate_count != 1:
            raise OnlyParameterSearchError("SEARCH_CANDIDATE_OUTPUT_INVALID", space.candidate_template_node_id)

    @staticmethod
    def _verify_bindings(
        experiment: OnlySearchExperimentManifestV3,
        space: OnlyParameterFactorSearchSpaceV1,
        policy: OnlyParameterSearchPolicyV1,
        algorithm: OnlyParameterSearchAlgorithmManifestV1,
        evaluation: OnlySymbolicResearchEvaluationContractV1,
        catalog: OnlyQuantAssetCatalogGeneration,
        dataset: OnlyVerifiedResearchDataset,
    ) -> None:
        if (
            experiment.search_space_reference.search_space_kind != PARAMETER_SEARCH_SPACE_KIND
            or experiment.search_space_reference.search_space_schema_version != space.schema_version
            or experiment.search_space_reference.search_space_fingerprint != space.search_space_fingerprint
            or experiment.search_policy_reference.policy_kind != PARAMETER_SEARCH_POLICY_KIND
            or experiment.search_policy_reference.policy_schema_version != policy.schema_version
            or experiment.search_policy_reference.policy_fingerprint != policy.policy_fingerprint
            or experiment.search_algorithm_binding.algorithm_id != algorithm.algorithm_id
            or experiment.search_algorithm_binding.algorithm_semantic_version != algorithm.algorithm_semantic_version
            or experiment.search_algorithm_binding.implementation_fingerprint != algorithm.implementation_fingerprint
            or experiment.search_algorithm_binding.source_revision != algorithm.source_revision
            or algorithm.algorithm_id != DETERMINISTIC_COARSE_TO_FINE_ALGORITHM_ID
            or algorithm.algorithm_semantic_version != DETERMINISTIC_COARSE_TO_FINE_ALGORITHM_SEMANTIC_VERSION
            or experiment.evaluation_context_reference.evaluation_kind != SYMBOLIC_EVALUATION_CONTRACT_KIND
            or experiment.evaluation_context_reference.evaluation_schema_version != evaluation.schema_version
            or experiment.evaluation_context_reference.evaluation_fingerprint
            != evaluation.evaluation_contract_fingerprint
            or experiment.catalog_generation_fingerprint != space.catalog_generation_fingerprint
            or catalog.generation_fingerprint != experiment.catalog_generation_fingerprint
            or dataset.snapshot.snapshot_fingerprint != experiment.dataset_snapshot_fingerprint
            or evaluation.dataset_snapshot_fingerprint != experiment.dataset_snapshot_fingerprint
            or space.sweep_definition.dataset_snapshot_fingerprint != experiment.dataset_snapshot_fingerprint
            or experiment.randomness_mode is not OnlySearchRandomnessMode.NONE
            or experiment.seed is not None
            or experiment.decision_engine_binding.mode is not OnlySearchDecisionMode.DETERMINISTIC
        ):
            raise OnlyParameterSearchError("SEARCH_CONTEXT_REFERENCE_INVALID", experiment.experiment_fingerprint)


__all__ = [name for name in globals() if name.startswith("Only")]
