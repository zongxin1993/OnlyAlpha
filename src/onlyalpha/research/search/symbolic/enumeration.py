"""Deterministic finite typed Calculation-graph enumeration V1."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import product

from onlyalpha.calculation import OnlyCalculationReference, OnlyOutputDefinition
from onlyalpha.calculation.compatibility import only_calculation_output_compatibility
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition, OnlyCalculationNodeDefinition
from onlyalpha.canonical import only_canonical_fingerprint

from .errors import OnlySymbolicSearchError
from .model import (
    OnlySymbolicCandidateOutputReferenceV1,
    OnlySymbolicComponentInstanceV1,
    OnlySymbolicGraphProposalV1,
)
from .verification import OnlyVerifiedSymbolicSearchSpaceV1


@dataclass(frozen=True, slots=True)
class OnlySymbolicGraphComplexityV1:
    node_count: int
    dependency_depth: int
    component_occurrences: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class OnlySymbolicEnumerationResultV1:
    proposals: tuple[OnlySymbolicGraphProposalV1, ...]
    search_space_exhausted: bool
    proposal_limit_reached: bool


@dataclass(frozen=True, slots=True)
class _AvailableOutput:
    nodes: tuple[OnlyCalculationNodeDefinition, ...]
    reference: OnlyCalculationReference
    output: OnlyOutputDefinition

    @property
    def graph_fingerprint(self) -> str:
        if not self.nodes:
            return ""
        return OnlyCalculationGraphDefinition(self.nodes).fingerprint

    @property
    def sort_key(self) -> tuple[object, ...]:
        return (
            len(self.nodes),
            self.graph_fingerprint,
            self.reference.node_fingerprint or "",
            self.reference.source or "",
            self.reference.output_name,
            self.output.name,
            self.output.semantic_type,
            self.output.unit or "",
        )


def symbolic_graph_complexity(
    graph: OnlyCalculationGraphDefinition,
    verified_space: OnlyVerifiedSymbolicSearchSpaceV1,
) -> OnlySymbolicGraphComplexityV1:
    """Measure only canonical Graph structure and exact component occurrences."""

    component_by_descriptor = {
        _definition_component_key(component): component.component_instance_fingerprint
        for component, _ in verified_space.component_types
    }
    occurrences: Counter[str] = Counter()
    by_fingerprint = {item.fingerprint: item for item in graph.nodes}
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

    for node in graph.nodes:
        key = _node_component_key(node)
        component_fingerprint = component_by_descriptor.get(key)
        if component_fingerprint is None:
            raise OnlySymbolicSearchError("SEARCH_GRAPH_ILLEGAL", "Graph contains a component outside the Search Space")
        occurrences[component_fingerprint] += 1
    return OnlySymbolicGraphComplexityV1(
        len(graph.nodes),
        max((depth(item.fingerprint) for item in graph.nodes), default=0),
        tuple(sorted(occurrences.items())),
    )


def enumerate_symbolic_factor_proposals(
    verified_space: OnlyVerifiedSymbolicSearchSpaceV1,
    *,
    proposal_limit: int,
) -> OnlySymbolicEnumerationResultV1:
    """Emit the exact deterministic prefix; downstream outcomes are not accepted inputs."""

    if isinstance(proposal_limit, bool) or not isinstance(proposal_limit, int) or proposal_limit <= 0:
        raise OnlySymbolicSearchError("SEARCH_PROPOSAL_LIMIT_REACHED", "proposal_limit must be positive")
    space = verified_space.search_space
    bounds = space.complexity_constraints
    terminals = tuple(
        sorted(
            (
                _AvailableOutput(
                    (),
                    OnlyCalculationReference(None, "value", reference.source_id),
                    OnlyOutputDefinition(
                        "value",
                        contract.data_type,
                        nullable,
                        contract.dimensions,
                        semantic_role,
                        contract.unit,
                    ),
                )
                for reference, contract, nullable in verified_space.source_contracts
                for semantic_role in sorted(contract.semantic_roles)
            ),
            key=lambda item: item.sort_key,
        )
    )
    available_by_count: dict[int, tuple[_AvailableOutput, ...]] = {0: terminals}
    all_candidates: list[OnlySymbolicGraphProposalV1] = []
    candidate_keys: set[tuple[str, str, str]] = set()

    for requested_count in range(1, bounds.max_nodes + 1):
        prior = tuple(
            item
            for count in sorted(available_by_count)
            if count < requested_count
            for item in available_by_count[count]
        )
        produced: dict[tuple[str, str, str], _AvailableOutput] = {}
        for component, type_definition in verified_space.component_types:
            choices: list[tuple[_AvailableOutput, ...]] = []
            impossible = False
            for input_contract in type_definition.inputs:
                compatible = tuple(
                    item
                    for item in prior
                    if only_calculation_output_compatibility(item.output, input_contract).compatible
                )
                if not compatible:
                    impossible = True
                    break
                choices.append(tuple(sorted(compatible, key=lambda item: item.sort_key)))
            if impossible:
                continue
            combinations = product(*choices) if choices else ((),)
            for selected in combinations:
                nodes_by_fingerprint = {node.fingerprint: node for item in selected for node in item.nodes}
                bindings = {
                    contract.name: item.reference
                    for contract, item in zip(type_definition.inputs, selected, strict=True)
                }
                try:
                    definition = verified_space.calculation_registry.rematerialize_definition(
                        component.type_reference,
                        component.normalized_parameters,
                        bindings,
                    )
                    if definition.fingerprint in nodes_by_fingerprint:
                        continue
                    graph = OnlyCalculationGraphDefinition(
                        (*nodes_by_fingerprint.values(), OnlyCalculationNodeDefinition(definition))
                    )
                    if len(graph.nodes) != requested_count:
                        continue
                    complexity = symbolic_graph_complexity(graph, verified_space)
                    if complexity.dependency_depth > bounds.max_depth or any(
                        count > bounds.max_occurrences_per_component for _, count in complexity.component_occurrences
                    ):
                        continue
                except (TypeError, ValueError, OnlySymbolicSearchError):
                    # Calculation remains final legality authority; invalid attempts are not formal Proposals.
                    continue
                node = next(item for item in graph.nodes if item.fingerprint == definition.fingerprint)
                for output in definition.outputs:
                    available = _AvailableOutput(
                        graph.nodes,
                        OnlyCalculationReference(node.fingerprint, output.name),
                        output,
                    )
                    produced[(graph.fingerprint, node.fingerprint, output.name)] = available
                    if (
                        component.component_instance_fingerprint
                        == space.candidate_output_contract.component_instance_fingerprint
                        and output.name == space.candidate_output_contract.output_name
                    ):
                        proposal = OnlySymbolicGraphProposalV1(
                            space.search_space_fingerprint,
                            graph,
                            OnlySymbolicCandidateOutputReferenceV1(node.fingerprint, output.name),
                        )
                        duplicate_key = (graph.fingerprint, node.fingerprint, output.name)
                        if duplicate_key not in candidate_keys:
                            candidate_keys.add(duplicate_key)
                            all_candidates.append(proposal)
        available_by_count[requested_count] = tuple(sorted(produced.values(), key=lambda item: item.sort_key))
        ordered = tuple(sorted(all_candidates, key=lambda item: _proposal_order(item, verified_space)))
    ordered = tuple(sorted(all_candidates, key=lambda item: _proposal_order(item, verified_space)))
    return OnlySymbolicEnumerationResultV1(
        ordered[:proposal_limit],
        len(ordered) <= proposal_limit,
        len(ordered) >= proposal_limit,
    )


def _proposal_order(
    proposal: OnlySymbolicGraphProposalV1,
    verified_space: OnlyVerifiedSymbolicSearchSpaceV1,
) -> tuple[object, ...]:
    complexity = symbolic_graph_complexity(proposal.graph, verified_space)
    component_fingerprints = tuple(
        sorted(
            _component_for_node(node, verified_space).component_instance_fingerprint
            for node in proposal.graph.ordered_nodes
        )
    )
    bindings = tuple(
        (
            node.fingerprint,
            tuple(
                sorted(
                    (
                        name,
                        reference.node_fingerprint or "",
                        reference.source or "",
                        reference.output_name,
                    )
                    for name, reference in node.definition.input_bindings.items()
                )
            ),
        )
        for node in proposal.graph.ordered_nodes
    )
    return (
        complexity.node_count,
        complexity.dependency_depth,
        component_fingerprints,
        only_canonical_fingerprint(bindings),
        proposal.graph.fingerprint,
        proposal.candidate_output_reference.node_fingerprint,
        proposal.candidate_output_reference.output_name,
    )


def _component_for_node(
    node: OnlyCalculationNodeDefinition,
    verified_space: OnlyVerifiedSymbolicSearchSpaceV1,
) -> OnlySymbolicComponentInstanceV1:
    key = _node_component_key(node)
    for component, _ in verified_space.component_types:
        if _definition_component_key(component) == key:
            return component
    raise OnlySymbolicSearchError("SEARCH_GRAPH_ILLEGAL", node.fingerprint)


def _definition_component_key(component: OnlySymbolicComponentInstanceV1) -> tuple[object, ...]:
    reference = component.type_reference
    return (
        reference.kind,
        reference.type_id,
        reference.semantic_version,
        tuple(component.normalized_parameters.items()),
    )


def _node_component_key(node: OnlyCalculationNodeDefinition) -> tuple[object, ...]:
    definition = node.definition
    return (definition.kind, definition.type_id, definition.semantic_version, tuple(definition.parameters.items()))


__all__ = [
    "OnlySymbolicEnumerationResultV1",
    "OnlySymbolicGraphComplexityV1",
    "enumerate_symbolic_factor_proposals",
    "symbolic_graph_complexity",
]
