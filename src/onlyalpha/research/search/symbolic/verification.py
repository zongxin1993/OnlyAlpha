"""Exact Catalog, Experiment and Proposal closure for symbolic search."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.calculation import (
    FACTOR_SCORE_SEMANTIC_TYPE,
    FACTOR_VALUE_SEMANTIC_TYPE,
    OnlyCalculationBackendKind,
    OnlyCalculationKind,
    OnlyCalculationTypeDefinition,
)
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.quant_assets import OnlyQuantAssetCatalogGeneration, OnlyQuantAssetLayer, OnlyQuantAssetProvider
from onlyalpha.research.experiment import (
    OnlySearchDecisionMode,
    OnlySearchExperimentManifestV1,
    OnlySearchIterationPlanV1,
    OnlySearchRandomnessMode,
)

from .errors import OnlySymbolicSearchError
from .model import (
    DETERMINISTIC_ENUMERATION_ALGORITHM_ID,
    DETERMINISTIC_ENUMERATION_ALGORITHM_SEMANTIC_VERSION,
    SYMBOLIC_PROPOSAL_KIND,
    SYMBOLIC_PROPOSAL_SCHEMA_VERSION,
    SYMBOLIC_SEARCH_SPACE_KIND,
    SYMBOLIC_SEARCH_SPACE_SCHEMA_VERSION,
    OnlySymbolicComponentInstanceV1,
    OnlySymbolicFactorSearchSpaceV1,
    OnlySymbolicGraphProposalV1,
)


@dataclass(frozen=True, slots=True)
class OnlyVerifiedSymbolicSearchSpaceV1:
    search_space: OnlySymbolicFactorSearchSpaceV1
    catalog_generation: OnlyQuantAssetCatalogGeneration
    calculation_registry: OnlyCalculationRegistry
    component_types: tuple[tuple[OnlySymbolicComponentInstanceV1, OnlyCalculationTypeDefinition], ...]
    factor_bridge: OnlySymbolicComponentInstanceV1


def verify_symbolic_search_space(
    search_space: OnlySymbolicFactorSearchSpaceV1,
    catalog_generation: OnlyQuantAssetCatalogGeneration,
) -> OnlyVerifiedSymbolicSearchSpaceV1:
    """Prove an exact finite Search Space against one immutable Catalog Generation."""

    if catalog_generation.generation_fingerprint != search_space.catalog_generation_fingerprint:
        raise OnlySymbolicSearchError(
            "SEARCH_COMPONENT_NOT_IN_CATALOG", "Search Space binds a different Catalog Generation"
        )
    registry = catalog_generation.calculation_registry()
    provider_by_type: dict[tuple[object, str, str], OnlyQuantAssetProvider] = {}
    for provider in catalog_generation.providers:
        for registration in provider.calculation_registrations:
            definition = registration.type_definition
            provider_by_type[(definition.kind, definition.type_id, definition.semantic_version)] = provider

    resolved: list[tuple[OnlySymbolicComponentInstanceV1, OnlyCalculationTypeDefinition]] = []
    bridges: list[OnlySymbolicComponentInstanceV1] = []
    for component in search_space.component_instances:
        reference = component.type_reference
        key = (reference.kind, reference.type_id, reference.semantic_version)
        exact_provider = provider_by_type.get(key)
        if exact_provider is None:
            raise OnlySymbolicSearchError(
                "SEARCH_COMPONENT_NOT_IN_CATALOG",
                f"{reference.type_id}@{reference.semantic_version}",
            )
        layer = exact_provider.manifest.layer
        is_bridge = component.component_instance_fingerprint == (
            search_space.candidate_output_contract.component_instance_fingerprint
        )
        if is_bridge:
            if layer is not OnlyQuantAssetLayer.FACTOR or reference.kind is not OnlyCalculationKind.FACTOR:
                raise OnlySymbolicSearchError(
                    "SEARCH_CANDIDATE_OUTPUT_INVALID", "candidate component is not an admitted L3 Factor"
                )
            bridges.append(component)
        elif layer not in {OnlyQuantAssetLayer.OPERATOR, OnlyQuantAssetLayer.INDICATOR}:
            raise OnlySymbolicSearchError(
                "SEARCH_COMPONENT_LAYER_FORBIDDEN",
                f"{reference.type_id}@{reference.semantic_version} belongs to {layer.value}",
            )
        try:
            type_definition = registry.resolve_type(reference)
        except ValueError as exc:
            raise OnlySymbolicSearchError("SEARCH_COMPONENT_NOT_IN_CATALOG", str(exc)) from exc
        try:
            registry.resolve(
                reference.kind,
                reference.type_id,
                reference.semantic_version,
                OnlyCalculationBackendKind.RESEARCH,
            )
        except ValueError as exc:
            raise OnlySymbolicSearchError("SEARCH_COMPONENT_RESEARCH_BACKEND_MISSING", str(exc)) from exc
        try:
            normalized = type_definition.parameters.normalize(component.normalized_parameters)
        except (TypeError, ValueError) as exc:
            raise OnlySymbolicSearchError("SEARCH_PARAMETER_ASSIGNMENT_INVALID", str(exc)) from exc
        if dict(normalized) != dict(component.normalized_parameters):
            raise OnlySymbolicSearchError(
                "SEARCH_PARAMETER_ASSIGNMENT_INVALID", "parameters are not exactly normalized"
            )
        resolved.append((component, type_definition))

    if len(bridges) != 1:
        raise OnlySymbolicSearchError(
            "SEARCH_CANDIDATE_OUTPUT_INVALID", "Search Space requires one exact admitted Factor bridge"
        )
    bridge_definition = next(definition for component, definition in resolved if component is bridges[0])
    output = next(
        (item for item in bridge_definition.outputs if item.name == search_space.candidate_output_contract.output_name),
        None,
    )
    if output is None or output.semantic_type not in {FACTOR_VALUE_SEMANTIC_TYPE, FACTOR_SCORE_SEMANTIC_TYPE}:
        raise OnlySymbolicSearchError(
            "SEARCH_CANDIDATE_OUTPUT_INVALID", "Factor bridge output is not a formal Factor value/score"
        )
    return OnlyVerifiedSymbolicSearchSpaceV1(
        search_space,
        catalog_generation,
        registry,
        tuple(sorted(resolved, key=lambda item: item[0].component_instance_fingerprint)),
        bridges[0],
    )


def verify_symbolic_experiment_binding(
    experiment: OnlySearchExperimentManifestV1,
    search_space: OnlySymbolicFactorSearchSpaceV1,
) -> None:
    reference = experiment.search_space_reference
    if (
        reference.search_space_kind != SYMBOLIC_SEARCH_SPACE_KIND
        or reference.search_space_schema_version != SYMBOLIC_SEARCH_SPACE_SCHEMA_VERSION
        or reference.search_space_fingerprint != search_space.search_space_fingerprint
        or experiment.catalog_generation_fingerprint != search_space.catalog_generation_fingerprint
    ):
        raise OnlySymbolicSearchError("SEARCH_SPACE_INVALID", "Experiment/Search Space exact binding differs")
    algorithm = experiment.search_algorithm_binding
    if (
        algorithm.algorithm_id != DETERMINISTIC_ENUMERATION_ALGORITHM_ID
        or algorithm.algorithm_semantic_version != DETERMINISTIC_ENUMERATION_ALGORITHM_SEMANTIC_VERSION
    ):
        raise OnlySymbolicSearchError(
            "SEARCH_ALGORITHM_INVALID",
            "B3.2 requires the exact deterministic-enumeration algorithm binding",
        )
    if experiment.randomness_mode is not OnlySearchRandomnessMode.NONE or experiment.seed is not None:
        raise OnlySymbolicSearchError(
            "SEARCH_RANDOMNESS_INVALID",
            "B3.2 deterministic enumeration requires randomness NONE and a null seed",
        )
    if experiment.decision_engine_binding.mode is not OnlySearchDecisionMode.DETERMINISTIC:
        raise OnlySymbolicSearchError(
            "SEARCH_DECISION_ENGINE_INVALID",
            "B3.2 proposal generation requires the deterministic decision-engine binding",
        )


def verify_symbolic_iteration_proposal_binding(
    plan: OnlySearchIterationPlanV1,
    proposal: OnlySymbolicGraphProposalV1,
    *,
    expected_search_space_fingerprint: str,
) -> None:
    if (
        plan.proposal_kind != SYMBOLIC_PROPOSAL_KIND
        or plan.proposal_schema_version != SYMBOLIC_PROPOSAL_SCHEMA_VERSION
        or plan.proposal_fingerprint != proposal.proposal_fingerprint
        or proposal.search_space_fingerprint != expected_search_space_fingerprint
    ):
        raise OnlySymbolicSearchError("SEARCH_INVALID_PROPOSAL", "Iteration/Proposal exact binding differs")


def verify_symbolic_proposal_space_closure(
    proposal: OnlySymbolicGraphProposalV1,
    search_space: OnlySymbolicFactorSearchSpaceV1,
) -> None:
    """Prove a persisted Proposal contains only its Space and exact candidate bridge."""

    if proposal.search_space_fingerprint != search_space.search_space_fingerprint:
        raise OnlySymbolicSearchError("SEARCH_INVALID_PROPOSAL", "Proposal belongs to a different Search Space")
    components = {
        (
            item.type_reference.kind,
            item.type_reference.type_id,
            item.type_reference.semantic_version,
            tuple(item.normalized_parameters.items()),
        ): item
        for item in search_space.component_instances
    }
    occurrences: dict[str, int] = {}
    by_fingerprint = {item.fingerprint: item for item in proposal.graph.nodes}
    memo: dict[str, int] = {}

    def depth(fingerprint: str) -> int:
        if fingerprint in memo:
            return memo[fingerprint]
        dependencies = tuple(
            reference.node_fingerprint
            for reference in by_fingerprint[fingerprint].definition.input_bindings.values()
            if reference.node_fingerprint is not None
        )
        value = 1 + max((depth(item) for item in dependencies), default=0)
        memo[fingerprint] = value
        return value

    candidate_component = None
    for node in proposal.graph.nodes:
        definition = node.definition
        component = components.get(
            (
                definition.kind,
                definition.type_id,
                definition.semantic_version,
                tuple(definition.parameters.items()),
            )
        )
        if component is None:
            raise OnlySymbolicSearchError("SEARCH_GRAPH_ILLEGAL", "Proposal contains an unbound component")
        fingerprint = component.component_instance_fingerprint
        occurrences[fingerprint] = occurrences.get(fingerprint, 0) + 1
        if node.fingerprint == proposal.candidate_output_reference.node_fingerprint:
            candidate_component = component
    constraints = search_space.complexity_constraints
    if (
        len(proposal.graph.nodes) > constraints.max_nodes
        or max((depth(item.fingerprint) for item in proposal.graph.nodes), default=0) > constraints.max_depth
        or any(value > constraints.max_occurrences_per_component for value in occurrences.values())
    ):
        raise OnlySymbolicSearchError("SEARCH_GRAPH_ILLEGAL", "Proposal exceeds canonical Graph complexity bounds")
    if (
        candidate_component is None
        or candidate_component.component_instance_fingerprint
        != search_space.candidate_output_contract.component_instance_fingerprint
        or proposal.candidate_output_reference.output_name != search_space.candidate_output_contract.output_name
    ):
        raise OnlySymbolicSearchError(
            "SEARCH_CANDIDATE_OUTPUT_INVALID", "Proposal candidate output differs from Search Space"
        )


__all__ = [name for name in globals() if name.startswith(("OnlyVerified", "verify_symbolic"))]
