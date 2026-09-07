from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from onlyalpha.calculation import OnlyCalculationKind, OnlyCalculationTypeReference
from onlyalpha.research.search.symbolic import (
    OnlySymbolicComponentInstanceV1,
    OnlySymbolicSearchError,
    enumerate_symbolic_factor_proposals,
    symbolic_graph_complexity,
    verify_symbolic_search_space,
)

from .support import space, verified_dataset


def test_catalog_closure_allows_l1_l2_and_one_exact_l3_bridge() -> None:
    generation, search_space = space()
    verified = verify_symbolic_search_space(search_space, generation, verified_dataset())
    assert verified.factor_bridge.type_reference.kind is OnlyCalculationKind.FACTOR
    assert {item.type_reference.type_id for item, _ in verified.component_types} == {
        "onlyalpha.operator.abs",
        "onlyalpha.indicator.rolling_return",
        "example.factor.momentum",
    }


def test_unknown_version_and_non_normal_parameter_fail_closed() -> None:
    generation, search_space = space()
    first = search_space.component_instances[0]
    wrong_version = OnlySymbolicComponentInstanceV1(
        OnlyCalculationTypeReference(first.type_reference.kind, first.type_reference.type_id, "999"),
        first.normalized_parameters,
    )
    with pytest.raises(OnlySymbolicSearchError) as unknown:
        verify_symbolic_search_space(
            replace(search_space, component_instances=(wrong_version, *search_space.component_instances[1:])),
            generation,
            verified_dataset(),
        )
    assert unknown.value.code == "SEARCH_COMPONENT_NOT_IN_CATALOG"

    indicator = next(
        item for item in search_space.component_instances if item.type_reference.type_id.endswith("rolling_return")
    )
    non_normal = replace(indicator, normalized_parameters={"period": 2})
    with pytest.raises(OnlySymbolicSearchError) as invalid:
        verify_symbolic_search_space(
            replace(
                search_space,
                component_instances=tuple(
                    non_normal if item is indicator else item for item in search_space.component_instances
                ),
            ),
            generation,
            verified_dataset(),
        )
    assert invalid.value.code == "SEARCH_PARAMETER_ASSIGNMENT_INVALID"


def test_ordered_enumeration_is_physical_order_invariant_and_prefix_stable() -> None:
    generation, search_space = space()
    reversed_generation, reversed_space = space(reverse=True)
    first = enumerate_symbolic_factor_proposals(
        verify_symbolic_search_space(search_space, generation, verified_dataset()), proposal_limit=8
    )
    second = enumerate_symbolic_factor_proposals(
        verify_symbolic_search_space(reversed_space, reversed_generation, verified_dataset()), proposal_limit=8
    )
    prefix = enumerate_symbolic_factor_proposals(
        verify_symbolic_search_space(search_space, generation, verified_dataset()), proposal_limit=7
    )
    assert [item.proposal_fingerprint for item in first.proposals] == [
        item.proposal_fingerprint for item in second.proposals
    ]
    assert [item.graph_fingerprint for item in first.proposals] == [item.graph_fingerprint for item in second.proposals]
    assert first.proposals[:7] == prefix.proposals
    assert len({(item.graph_fingerprint, item.candidate_output_reference) for item in first.proposals}) == len(
        first.proposals
    )


def test_complexity_uses_canonical_graph_and_enforces_depth_occurrence() -> None:
    generation, search_space = space(max_nodes=3, max_depth=1, max_occurrences=1)
    verified = verify_symbolic_search_space(search_space, generation, verified_dataset())
    result = enumerate_symbolic_factor_proposals(verified, proposal_limit=100)
    assert result.search_space_exhausted
    assert result.proposals
    for proposal in result.proposals:
        complexity = symbolic_graph_complexity(proposal.graph, verified)
        assert complexity.node_count <= 3
        assert complexity.dependency_depth <= 1
        assert all(count <= 1 for _, count in complexity.component_occurrences)


def test_enumerator_signature_has_no_research_or_qualification_feedback() -> None:
    import inspect

    parameters = set(inspect.signature(enumerate_symbolic_factor_proposals).parameters)
    assert parameters == {"verified_space", "proposal_limit"}


def test_fresh_process_reenumeration_has_identical_ordered_proposal_and_graph_sequences() -> None:
    program = """
import json
from tests.research.search.symbolic.support import space, verified_dataset
from onlyalpha.research.search.symbolic import verify_symbolic_search_space, enumerate_symbolic_factor_proposals
generation, search_space = space()
result = enumerate_symbolic_factor_proposals(verify_symbolic_search_space(search_space, generation, verified_dataset()), proposal_limit=10)
print(json.dumps({"proposals": [x.proposal_fingerprint for x in result.proposals], "graphs": [x.graph_fingerprint for x in result.proposals]}))
"""
    first = json.loads(subprocess.check_output([sys.executable, "-c", program], text=True))
    second = json.loads(subprocess.check_output([sys.executable, "-c", program], text=True))
    assert first == second
    assert first["proposals"] and first["graphs"]


@settings(max_examples=12, deadline=None)
@given(
    proposal_limit=st.integers(min_value=1, max_value=12),
    max_nodes=st.integers(min_value=1, max_value=3),
    reverse=st.booleans(),
)
def test_canonical_input_permutations_preserve_every_generated_prefix(
    proposal_limit: int,
    max_nodes: int,
    reverse: bool,
) -> None:
    generation, search_space = space(max_nodes=max_nodes, reverse=reverse)
    canonical_generation, canonical_space = space(max_nodes=max_nodes, reverse=False)
    actual = enumerate_symbolic_factor_proposals(
        verify_symbolic_search_space(search_space, generation, verified_dataset()),
        proposal_limit=proposal_limit,
    )
    canonical = enumerate_symbolic_factor_proposals(
        verify_symbolic_search_space(canonical_space, canonical_generation, verified_dataset()),
        proposal_limit=proposal_limit,
    )
    expanded = enumerate_symbolic_factor_proposals(
        verify_symbolic_search_space(canonical_space, canonical_generation, verified_dataset()),
        proposal_limit=proposal_limit + 1,
    )

    assert actual == canonical
    assert canonical.proposals == expanded.proposals[:proposal_limit]
