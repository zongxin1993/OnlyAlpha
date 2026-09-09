from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from onlyalpha.application.search_generation_execution import OnlyHistoricalGenerationExecutionMismatch
from onlyalpha.application.search_product import OnlySearchMethodV1
from onlyalpha.research.experiment.errors import OnlySearchProvenanceStoreError
from onlyalpha.research.search.symbolic.enumeration import enumerate_symbolic_factor_proposals
from onlyalpha.research.search.symbolic.enumeration_result import OnlySymbolicEnumerationResultV1
from onlyalpha.research.search.symbolic.errors import OnlySymbolicSearchError
from onlyalpha.research.search.symbolic.execution import verify_hosted_specification_binding
from onlyalpha.research.search.symbolic.verification import (
    verify_symbolic_proposal_reconstruction,
    verify_symbolic_search_space,
)
from onlyalpha.research.specification import OnlyResearchSpecification, OnlyResearchSpecificationResolver
from tests.research.specification.support import registry

from .support import space, verified_dataset
from .test_search_product_adapter import _case


def _resolved_case(tmp_path: Path):  # type: ignore[no-untyped-def]
    _, query, _, _, command = _case(tmp_path)
    adapter = query._adapters[OnlySearchMethodV1.SYMBOLIC]
    experiment = adapter.derive_submit_experiment(command)
    adapter._store.commit_search_space(command.search_space)
    adapter._store.commit_evaluation_contract(command.evaluation_contract)
    adapter._store.commit_algorithm_implementation_manifest(command.algorithm_manifest)
    facts = adapter._contexts.resolve_historical_facts(experiment)
    execution, _ = adapter._generation_execution.derive_enumeration("f" * 64, facts)
    proposal = execution.proposals[0]
    resolved = adapter._generation_execution.resolve_research("f" * 64, facts, proposal)
    return adapter, command, experiment, facts, proposal, resolved


def _alpha_rename(value: object) -> object:
    if isinstance(value, str) and value.startswith("node_"):
        return "historical_" + value[5:]
    if isinstance(value, list):
        return [_alpha_rename(item) for item in value]
    if isinstance(value, dict):
        return {key: _alpha_rename(item) for key, item in value.items()}
    return value


def test_historical_template_identifiers_are_not_parent_runtime_semantics(tmp_path: Path) -> None:
    _, _, _, facts, proposal, resolved = _resolved_case(tmp_path)
    original = resolved.specification
    verify_hosted_specification_binding(original, facts.evaluation_contract, proposal)
    payload = _alpha_rename(original.to_dict())
    assert isinstance(payload, dict)
    renamed = OnlyResearchSpecification.from_dict(payload)
    resolver = OnlyResearchSpecificationResolver(registry())
    original_resolution = resolver.resolve(original)
    renamed_resolution = resolver.resolve(renamed)
    assert original.specification_fingerprint != renamed.specification_fingerprint
    assert tuple(
        (item.graph_fingerprint, item.calculation_fingerprint) for item in original_resolution.candidates
    ) == tuple((item.graph_fingerprint, item.calculation_fingerprint) for item in renamed_resolution.candidates)
    assert renamed_resolution.candidates[0].candidate_fingerprint is not None
    assert renamed_resolution.workload.result_plan.candidates[0].candidate_fingerprint == (
        renamed_resolution.candidates[0].candidate_fingerprint
    )
    verify_hosted_specification_binding(renamed, facts.evaluation_contract, proposal)


@pytest.mark.parametrize("change", ["statistics", "evidence", "proposal_node", "fixed_calculation"])
def test_canonical_binding_rejects_different_authored_semantics(tmp_path: Path, change: str) -> None:
    _, _, _, facts, proposal, resolved = _resolved_case(tmp_path)
    specification = resolved.specification
    if change == "statistics":
        statistics = specification.statistics
        specification = replace(
            specification, statistics=(replace(statistics[0], feature=statistics[0].target), *statistics[1:])
        )
    elif change == "evidence":
        evidence = specification.evidence
        assert evidence is not None
        specification = replace(
            specification,
            evidence=replace(evidence, published_series=(replace(evidence.published_series[0], output_name="other"),)),
        )
    elif change == "fixed_calculation":
        specification = replace(
            specification,
            calculations=tuple(
                item
                for item in specification.calculations
                if item.calculation_id == facts.evaluation_contract.candidate_calculation_id
            ),
        )
    else:
        candidate_id = facts.evaluation_contract.candidate_calculation_id
        calculation = next(item for item in specification.calculations if item.calculation_id == candidate_id)
        nodes = calculation.graph_template.nodes
        changed = replace(
            calculation,
            graph_template=replace(
                calculation.graph_template,
                nodes=(replace(nodes[0], parameters={**nodes[0].parameters, "changed": 1}), *nodes[1:]),
            ),
        )
        specification = replace(
            specification,
            calculations=tuple(
                changed if item.calculation_id == candidate_id else item for item in specification.calculations
            ),
        )
    with pytest.raises(OnlyHistoricalGenerationExecutionMismatch):
        verify_hosted_specification_binding(specification, facts.evaluation_contract, proposal)


def test_historical_read_view_cannot_admit_unknown_catalog_without_worker(tmp_path: Path) -> None:
    _, query, _, _, command = _case(tmp_path)
    adapter = query._adapters[OnlySearchMethodV1.SYMBOLIC]
    search_space = replace(command.search_space, catalog_generation_fingerprint="0" * 64)
    command = replace(command, search_space=search_space, catalog_generation_fingerprint="0" * 64)
    experiment = adapter.derive_submit_experiment(command)
    adapter._store.commit_search_space(search_space)
    adapter._store.commit_evaluation_contract(command.evaluation_contract)
    adapter._store.commit_algorithm_implementation_manifest(command.algorithm_manifest)
    with pytest.raises(OnlySymbolicSearchError) as executable_error:
        adapter._contexts.resolve_verified_context(experiment)
    assert executable_error.value.code == "SEARCH_CATALOG_REFERENCE_INVALID"
    with pytest.raises(OnlySearchProvenanceStoreError) as admission_error:
        adapter._provenance.commit_experiment(experiment)
    assert admission_error.value.code == "SEARCH_EXPERIMENT_UNVERIFIED"
    assert not tuple((tmp_path / "research/search-provenance/experiments").glob("**/manifest.json"))


def test_fact_context_cannot_publish_unverified_enumeration(tmp_path: Path) -> None:
    service, query, _, _, command = _case(tmp_path)
    service.submit(command)
    adapter = query._adapters[OnlySearchMethodV1.SYMBOLIC]
    experiment = adapter.derive_submit_experiment(command)
    facts = adapter._contexts.resolve_historical_facts(experiment)
    generation, loose_space = space(max_nodes=5, max_depth=5)
    proposals = enumerate_symbolic_factor_proposals(
        verify_symbolic_search_space(loose_space, generation, verified_dataset()),
        proposal_limit=100,
    ).proposals
    original = next(
        item for item in proposals if len(item.graph.nodes) > facts.search_space.complexity_constraints.max_nodes
    )
    proposal = replace(original, search_space_fingerprint=facts.search_space.search_space_fingerprint)
    adapter._store.commit_proposal(proposal)
    with pytest.raises(OnlySymbolicSearchError) as error:
        verify_symbolic_proposal_reconstruction(proposal, adapter._contexts.resolve_verified_context(experiment))
    assert error.value.code == "SEARCH_GRAPH_ILLEGAL"
    enumeration = OnlySymbolicEnumerationResultV1(
        experiment.experiment_fingerprint,
        facts.historical_algorithm_manifest.implementation_fingerprint,
        facts.search_space.search_space_fingerprint,
        experiment.search_budget.proposal_limit,
        (proposal.proposal_fingerprint,),
        False,
        True,
    )
    with pytest.raises(OnlySearchProvenanceStoreError) as error:
        adapter._store.commit_enumeration_result(enumeration, context=facts)
    assert error.value.code == "SEARCH_COMPUTATION_UNVERIFIED"
    assert not tuple((tmp_path / "research/symbolic-search/enumeration-results").glob("**/manifest.json"))
