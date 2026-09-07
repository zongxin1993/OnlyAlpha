"""Exact Catalog, Experiment and Proposal closure for symbolic search."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.calculation import (
    FACTOR_SCORE_SEMANTIC_TYPE,
    FACTOR_VALUE_SEMANTIC_TYPE,
    OnlyCalculationBackendKind,
    OnlyCalculationKind,
    OnlyCalculationTypeDefinition,
    OnlyCalculationTypeReference,
    OnlyOutputDefinition,
)
from onlyalpha.calculation.compatibility import only_calculation_output_compatibility
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition, OnlyCalculationNodeDefinition
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.quant_assets import OnlyQuantAssetCatalogGeneration, OnlyQuantAssetLayer, OnlyQuantAssetProvider
from onlyalpha.research.calculation.binding import (
    OnlyResearchDatasetSourceContractV1,
    only_research_dataset_source_contract,
)
from onlyalpha.research.dataset.ports import OnlyVerifiedResearchDataset
from onlyalpha.research.experiment import (
    OnlySearchDecisionMode,
    OnlySearchExperimentManifestV2,
    OnlySearchIterationPlanV1,
    OnlySearchRandomnessMode,
)

from .errors import OnlySymbolicSearchError
from .model import (
    DETERMINISTIC_ENUMERATION_ALGORITHM_ID,
    DETERMINISTIC_ENUMERATION_ALGORITHM_SEMANTIC_VERSION,
    SYMBOLIC_PROPOSAL_KIND,
    SYMBOLIC_PROPOSAL_SCHEMA_VERSION,
    SYMBOLIC_SEARCH_SPACE_CONTEXT_SCHEMA_VERSION,
    SYMBOLIC_SEARCH_SPACE_KIND,
    OnlySymbolicComponentInstanceV1,
    OnlySymbolicExternalSourceReferenceV1,
    OnlySymbolicFactorSearchSpaceV2,
    OnlySymbolicGraphProposalV1,
)


@dataclass(frozen=True, slots=True)
class OnlyVerifiedSymbolicSearchSpaceV1:
    search_space: OnlySymbolicFactorSearchSpaceV2
    catalog_generation: OnlyQuantAssetCatalogGeneration
    calculation_registry: OnlyCalculationRegistry
    component_types: tuple[tuple[OnlySymbolicComponentInstanceV1, OnlyCalculationTypeDefinition], ...]
    factor_bridge: OnlySymbolicComponentInstanceV1
    source_contracts: tuple[
        tuple[OnlySymbolicExternalSourceReferenceV1, OnlyResearchDatasetSourceContractV1, OnlyOutputDefinition], ...
    ]


def verify_symbolic_search_space(
    search_space: OnlySymbolicFactorSearchSpaceV2,
    catalog_generation: OnlyQuantAssetCatalogGeneration,
    verified_dataset: OnlyVerifiedResearchDataset,
) -> OnlyVerifiedSymbolicSearchSpaceV1:
    """Contextually prove Search Space against Catalog, Source contracts and exact Dataset."""

    if not isinstance(search_space, OnlySymbolicFactorSearchSpaceV2):
        raise OnlySymbolicSearchError("SEARCH_SPACE_SCHEMA_UNSUPPORTED", "B3.2 requires Search Space V2")

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
    source_contracts = []
    try:
        snapshot = verified_dataset.snapshot
        table = verified_dataset.table
        schema = snapshot.dataset_schema
    except AttributeError as exc:
        raise OnlySymbolicSearchError("SEARCH_DATASET_INVALID", "verified Dataset payload is incomplete") from exc
    for source_reference in search_space.external_source_terminals:
        contract = only_research_dataset_source_contract(source_reference.source_id)
        if contract is None:
            raise OnlySymbolicSearchError("SEARCH_SOURCE_CONTRACT_NOT_FOUND", source_reference.source_id)
        if contract.source_contract_fingerprint != source_reference.source_contract_fingerprint:
            raise OnlySymbolicSearchError("SEARCH_SOURCE_CONTRACT_MISMATCH", source_reference.source_id)
        try:
            authoritative_field = schema.arrow_schema.field(contract.column)
            table_field = table.schema.field(contract.column)
        except (KeyError, ValueError) as exc:
            raise OnlySymbolicSearchError("SEARCH_SOURCE_DATASET_INCOMPATIBLE", source_reference.source_id) from exc
        if authoritative_field != table_field:
            raise OnlySymbolicSearchError("SEARCH_SOURCE_DATASET_INCOMPATIBLE", source_reference.source_id)
        semantic_type = (
            "NUMERIC_SERIES" if "NUMERIC_SERIES" in contract.semantic_roles else min(contract.semantic_roles)
        )
        projection = OnlyOutputDefinition(
            "value",
            contract.data_type,
            authoritative_field.nullable,
            contract.dimensions,
            semantic_type,
            contract.unit,
        )
        source_contracts.append((source_reference, contract, projection))
    return OnlyVerifiedSymbolicSearchSpaceV1(
        search_space,
        catalog_generation,
        registry,
        tuple(sorted(resolved, key=lambda item: item[0].component_instance_fingerprint)),
        bridges[0],
        tuple(source_contracts),
    )


def verify_symbolic_experiment_binding(
    experiment: OnlySearchExperimentManifestV2,
    search_space: OnlySymbolicFactorSearchSpaceV2,
) -> None:
    if not isinstance(experiment, OnlySearchExperimentManifestV2):
        raise OnlySymbolicSearchError("SEARCH_EXPERIMENT_SCHEMA_UNSUPPORTED", "B3.2 requires Experiment V2")
    reference = experiment.search_space_reference
    if (
        reference.search_space_kind != SYMBOLIC_SEARCH_SPACE_KIND
        or reference.search_space_schema_version != SYMBOLIC_SEARCH_SPACE_CONTEXT_SCHEMA_VERSION
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
    search_space: OnlySymbolicFactorSearchSpaceV2,
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


@dataclass(frozen=True, slots=True)
class OnlyVerifiedSymbolicProposalV1:
    proposal: OnlySymbolicGraphProposalV1
    context: object
    graph: OnlyCalculationGraphDefinition
    candidate_node: OnlyCalculationNodeDefinition
    candidate_output: OnlyOutputDefinition
    complexity: object


def verify_symbolic_proposal_reconstruction(
    proposal: OnlySymbolicGraphProposalV1,
    context: object,
) -> OnlyVerifiedSymbolicProposalV1:
    """Reconstruct every persisted Definition through the exact Catalog Registry."""

    verified_space = getattr(context, "verified_search_space", None)
    if not isinstance(verified_space, OnlyVerifiedSymbolicSearchSpaceV1):
        raise OnlySymbolicSearchError("SEARCH_CONTEXT_INVALID", "Verified Search Context is required")
    verify_symbolic_proposal_space_closure(proposal, verified_space.search_space)
    components = {
        (
            item.type_reference.kind,
            item.type_reference.type_id,
            item.type_reference.semantic_version,
            tuple(item.normalized_parameters.items()),
        ): item
        for item, _ in verified_space.component_types
    }
    reconstructed = []
    source_outputs = {
        (reference.source_id, output.name): output for reference, _contract, output in verified_space.source_contracts
    }
    for node in proposal.graph.ordered_nodes:
        definition = node.definition
        key = (
            definition.kind,
            definition.type_id,
            definition.semantic_version,
            tuple(definition.parameters.items()),
        )
        component = components.get(key)
        if component is None:
            raise OnlySymbolicSearchError("SEARCH_PROPOSAL_RECONSTRUCTION_FAILED", "component is outside Search Space")
        input_contracts = {item.name: item for item in definition.inputs}
        for name, binding in definition.input_bindings.items():
            if binding.source is None:
                continue
            source_output = source_outputs.get((binding.source, binding.output_name))
            if (
                source_output is None
                or not only_calculation_output_compatibility(source_output, input_contracts[name]).compatible
            ):
                raise OnlySymbolicSearchError("SEARCH_PROPOSAL_SOURCE_BINDING_MISMATCH", node.fingerprint)
        try:
            authoritative = verified_space.calculation_registry.rematerialize_definition(
                OnlyCalculationTypeReference(
                    definition.kind,
                    definition.type_id,
                    definition.semantic_version,
                ),
                component.normalized_parameters,
                definition.input_bindings,
            )
        except (TypeError, ValueError) as exc:
            raise OnlySymbolicSearchError("SEARCH_PROPOSAL_RECONSTRUCTION_FAILED", node.fingerprint) from exc
        if authoritative.fingerprint != definition.fingerprint:
            raise OnlySymbolicSearchError("SEARCH_PROPOSAL_DEFINITION_MISMATCH", node.fingerprint)
        reconstructed.append(OnlyCalculationNodeDefinition(authoritative, node.alias))
    try:
        graph = OnlyCalculationGraphDefinition(tuple(reconstructed))
    except (TypeError, ValueError) as exc:
        raise OnlySymbolicSearchError("SEARCH_PROPOSAL_RECONSTRUCTION_FAILED", proposal.proposal_fingerprint) from exc
    if graph.fingerprint != proposal.graph_fingerprint:
        raise OnlySymbolicSearchError("SEARCH_PROPOSAL_GRAPH_MISMATCH", proposal.proposal_fingerprint)
    candidate = next(
        (item for item in graph.nodes if item.fingerprint == proposal.candidate_output_reference.node_fingerprint),
        None,
    )
    output = (
        None
        if candidate is None
        else next(
            (
                item
                for item in candidate.definition.outputs
                if item.name == proposal.candidate_output_reference.output_name
            ),
            None,
        )
    )
    if candidate is None or output is None:
        raise OnlySymbolicSearchError("SEARCH_CANDIDATE_OUTPUT_INVALID", proposal.proposal_fingerprint)
    # Local import avoids making the persistence/model layer depend on enumeration.
    from .enumeration import symbolic_graph_complexity

    complexity = symbolic_graph_complexity(graph, verified_space)
    return OnlyVerifiedSymbolicProposalV1(proposal, context, graph, candidate, output, complexity)


__all__ = [name for name in globals() if name.startswith(("OnlyVerified", "verify_symbolic"))]
