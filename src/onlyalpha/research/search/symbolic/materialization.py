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
from .evaluation import OnlySymbolicResearchEvaluationContractV1
from .verification import OnlyVerifiedSymbolicProposalV1


@dataclass(frozen=True, slots=True)
class OnlySymbolicResearchMaterializationV1:
    specification: OnlyResearchSpecification
    candidate_template_node_id: str
    candidate_output_name: str


def proposal_to_research_graph_template(
    verified_proposal: OnlyVerifiedSymbolicProposalV1,
) -> tuple[OnlyResearchGraphTemplate, str, str]:
    """Losslessly project a canonical Graph through the existing template vocabulary."""

    proposal = verified_proposal.proposal
    graph = verified_proposal.graph
    node_ids = {node.fingerprint: f"node_{node.fingerprint}" for node in graph.nodes}
    nodes = []
    for node in graph.ordered_nodes:
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
    evaluation: OnlySymbolicResearchEvaluationContractV1,
    verified_proposal: OnlyVerifiedSymbolicProposalV1,
) -> OnlySymbolicResearchMaterializationV1:
    context = verified_proposal.context
    if getattr(context, "evaluation_contract", None) != evaluation:
        raise OnlySymbolicSearchError("SEARCH_EVALUATION_CONTEXT_MISMATCH", evaluation.evaluation_contract_fingerprint)
    graph_template, candidate_node_id, candidate_output_name = proposal_to_research_graph_template(verified_proposal)
    candidate_id = evaluation.candidate_calculation_id
    calculations = (*evaluation.fixed_calculations, OnlyResearchCalculationSpec(candidate_id, graph_template))

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
        for item in evaluation.statistics
    )
    evidence = evaluation.evidence
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
        evaluation.dataset_snapshot_fingerprint,
        calculations,
        statistics,
        materialized_evidence,
        evaluation.research_specification_schema_version,
    )
    return OnlySymbolicResearchMaterializationV1(specification, candidate_node_id, candidate_output_name)


__all__ = [name for name in globals() if name.startswith(("OnlySymbolic", "materialize_", "proposal_to_"))]
