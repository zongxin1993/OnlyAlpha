"""Unique Graph Template to canonical Calculation Graph materialization."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from onlyalpha.calculation.definition import OnlyCalculationReference, OnlyCalculationScalar
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition, OnlyCalculationNodeDefinition
from onlyalpha.calculation.registry import OnlyCalculationRegistry

from .definition import OnlyResearchSweepParameterTarget
from .errors import OnlyResearchSweepError
from .template import OnlyResearchGraphTemplate


@dataclass(frozen=True, slots=True)
class OnlyResearchGraphMaterialization:
    """Ephemeral deterministic evidence; the Graph remains semantic authority."""

    graph: OnlyCalculationGraphDefinition
    node_fingerprints: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_fingerprints", MappingProxyType(dict(sorted(self.node_fingerprints.items()))))


class OnlyResearchGraphTemplateMaterializer:
    """The single implementation used by direct Specifications and Sweeps."""

    def __init__(self, calculation_registry: OnlyCalculationRegistry) -> None:
        if not isinstance(calculation_registry, OnlyCalculationRegistry):
            raise TypeError("Graph Template Materializer requires the Calculation Registry")
        self._registry = calculation_registry

    def materialize(
        self,
        template: OnlyResearchGraphTemplate,
        assignment: Mapping[OnlyResearchSweepParameterTarget, OnlyCalculationScalar] | None = None,
    ) -> OnlyResearchGraphMaterialization:
        if not isinstance(template, OnlyResearchGraphTemplate):
            raise OnlyResearchSweepError("SWEEP_TEMPLATE_INVALID", "materialize requires a Graph Template")
        assigned = dict(assignment or {})
        materialized: dict[str, OnlyCalculationNodeDefinition] = {}
        try:
            for template_node in template.ordered_nodes:
                parameters = dict(template_node.parameters)
                for target, value in assigned.items():
                    if target.template_node_id == template_node.template_node_id:
                        parameters[target.parameter_name] = value
                bindings: dict[str, OnlyCalculationReference] = {}
                for binding in template_node.input_bindings:
                    reference = binding.reference
                    if reference.template_node_id is None:
                        bindings[binding.input_name] = OnlyCalculationReference(
                            None, reference.output_name, reference.source
                        )
                    else:
                        upstream = materialized[reference.template_node_id]
                        bindings[binding.input_name] = OnlyCalculationReference(
                            upstream.fingerprint, reference.output_name
                        )
                resolved = self._registry.rematerialize_definition(template_node.type_reference, parameters, bindings)
                materialized[template_node.template_node_id] = OnlyCalculationNodeDefinition(
                    resolved, template_node.alias
                )
            graph = OnlyCalculationGraphDefinition(tuple(materialized.values()))
            return OnlyResearchGraphMaterialization(
                graph,
                {template_id: node.fingerprint for template_id, node in materialized.items()},
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise OnlyResearchSweepError("SWEEP_MATERIALIZATION_FAILED", str(exc)) from exc
