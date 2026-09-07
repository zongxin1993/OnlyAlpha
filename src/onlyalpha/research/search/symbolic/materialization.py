"""Projection of a formal symbolic Proposal into the existing Research contract."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.calculation import OnlyCalculationTypeReference
from onlyalpha.research.specification.model import (
    OnlyResearchCalculationSpec,
    OnlyResearchScientificEvidenceSpec,
    OnlyResearchSeriesSelector,
    OnlyResearchSignalEvidenceSpec,
    OnlyResearchSpecification,
    OnlyResearchStatisticsSpec,
)
from onlyalpha.research.sweep.template import (
    OnlyResearchGraphTemplate,
    OnlyResearchGraphTemplateNode,
    OnlyResearchTemplateInputBinding,
    OnlyResearchTemplateReference,
)

from .errors import OnlySymbolicSearchError
from .model import OnlySymbolicGraphProposalV1


@dataclass(frozen=True, slots=True)
class OnlySymbolicResearchEvaluationTemplateV1:
    """One fixed normal Research Specification with a replaceable Candidate graph."""

    specification: OnlyResearchSpecification
    candidate_calculation_id: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not self.candidate_calculation_id:
            raise ValueError("SEARCH_EVALUATION_TEMPLATE_INVALID")
        matches = tuple(
            item for item in self.specification.calculations if item.calculation_id == self.candidate_calculation_id
        )
        if len(matches) != 1:
            raise ValueError("SEARCH_EVALUATION_TEMPLATE_INVALID")
        if (
            self.specification.evidence is None
            or self.specification.evidence.candidate_calculation_id != self.candidate_calculation_id
        ):
            raise ValueError("SEARCH_EVALUATION_TEMPLATE_INVALID")


@dataclass(frozen=True, slots=True)
class OnlySymbolicResearchMaterializationV1:
    specification: OnlyResearchSpecification
    candidate_template_node_id: str
    candidate_output_name: str


def proposal_to_research_graph_template(
    proposal: OnlySymbolicGraphProposalV1,
) -> tuple[OnlyResearchGraphTemplate, str, str]:
    """Losslessly project a canonical Graph through the existing template vocabulary."""

    node_ids = {node.fingerprint: f"node_{node.fingerprint}" for node in proposal.graph.nodes}
    nodes = []
    for node in proposal.graph.ordered_nodes:
        definition = node.definition
        bindings = tuple(
            OnlyResearchTemplateInputBinding(
                name,
                OnlyResearchTemplateReference(
                    None if reference.node_fingerprint is None else node_ids[reference.node_fingerprint],
                    reference.output_name,
                    reference.source,
                ),
            )
            for name, reference in definition.input_bindings.items()
        )
        nodes.append(
            OnlyResearchGraphTemplateNode(
                node_ids[node.fingerprint],
                OnlyCalculationTypeReference(definition.kind, definition.type_id, definition.semantic_version),
                definition.parameters,
                bindings,
                node.alias,
            )
        )
    candidate_id = node_ids[proposal.candidate_output_reference.node_fingerprint]
    return OnlyResearchGraphTemplate(tuple(nodes)), candidate_id, proposal.candidate_output_reference.output_name


def materialize_symbolic_research_specification(
    template: OnlySymbolicResearchEvaluationTemplateV1,
    proposal: OnlySymbolicGraphProposalV1,
) -> OnlySymbolicResearchMaterializationV1:
    graph_template, candidate_node_id, candidate_output_name = proposal_to_research_graph_template(proposal)
    candidate_id = template.candidate_calculation_id
    calculations = tuple(
        OnlyResearchCalculationSpec(candidate_id, graph_template) if item.calculation_id == candidate_id else item
        for item in template.specification.calculations
    )

    def selector(value: OnlyResearchSeriesSelector) -> OnlyResearchSeriesSelector:
        if value.calculation_id != candidate_id:
            return value
        return OnlyResearchSeriesSelector(candidate_id, candidate_node_id, candidate_output_name)

    statistics = tuple(
        OnlyResearchStatisticsSpec(
            selector(item.feature),
            selector(item.target),
            item.definition,
            item.expansion,
        )
        for item in template.specification.statistics
    )
    evidence = template.specification.evidence
    if evidence is None:  # guarded by the template contract
        raise OnlySymbolicSearchError("SEARCH_EVALUATION_TEMPLATE_INVALID", "scientific evidence is required")
    signals = evidence.signals
    materialized_evidence = OnlyResearchScientificEvidenceSpec(
        candidate_id,
        tuple(selector(item) for item in evidence.published_series),
        OnlyResearchSignalEvidenceSpec(
            None if signals.eligibility is None else selector(signals.eligibility),
            None if signals.entry is None else selector(signals.entry),
            None if signals.exit is None else selector(signals.exit),
        ),
    )
    specification = OnlyResearchSpecification(
        template.specification.dataset_snapshot_fingerprint,
        calculations,
        statistics,
        materialized_evidence,
        template.specification.schema_version,
    )
    return OnlySymbolicResearchMaterializationV1(specification, candidate_node_id, candidate_output_name)


__all__ = [name for name in globals() if name.startswith(("OnlySymbolic", "materialize_", "proposal_to_"))]
