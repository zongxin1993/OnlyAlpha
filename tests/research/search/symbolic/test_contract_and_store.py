from __future__ import annotations

import json
from dataclasses import replace

import pytest

from onlyalpha.research.search.symbolic import (
    OnlyJsonSymbolicSearchStore,
    OnlySymbolicCandidateOutputContractV1,
    OnlySymbolicSearchStoreError,
    enumerate_symbolic_factor_proposals,
    verify_symbolic_search_space,
)

from .support import space


def test_search_space_identity_is_canonical_and_semantic_changes_are_distinct(tmp_path) -> None:
    generation, first = space()
    _, perturbed = space(reverse=True)
    assert first.search_space_fingerprint == perturbed.search_space_fingerprint
    assert first == type(first).from_dict(first.to_dict())
    assert (
        replace(
            first,
            complexity_constraints=replace(first.complexity_constraints, max_nodes=4),
        ).search_space_fingerprint
        != first.search_space_fingerprint
    )
    assert (
        replace(
            first,
            candidate_output_contract=OnlySymbolicCandidateOutputContractV1(
                first.candidate_output_contract.component_instance_fingerprint,
                "missing",
            ),
        ).search_space_fingerprint
        != first.search_space_fingerprint
    )

    store = OnlyJsonSymbolicSearchStore(tmp_path)
    created = store.commit_search_space(first)
    reused = store.commit_search_space(first)
    assert created.disposition.value == "CREATED"
    assert reused.disposition.value == "REUSED"
    assert store.load_search_space_verified(first.search_space_fingerprint) == first
    assert generation.generation_fingerprint == first.catalog_generation_fingerprint


def test_proposal_identity_domains_and_verified_corruption_failure(tmp_path) -> None:
    generation, search_space = space(max_nodes=1)
    proposal = enumerate_symbolic_factor_proposals(
        verify_symbolic_search_space(search_space, generation), proposal_limit=1
    ).proposals[0]
    assert proposal == type(proposal).from_dict(proposal.to_dict())
    assert proposal.proposal_fingerprint != proposal.graph_fingerprint

    store = OnlyJsonSymbolicSearchStore(tmp_path)
    store.commit_search_space(search_space)
    store.commit_proposal(proposal)
    target = (
        tmp_path
        / "research"
        / "symbolic-search"
        / "proposals"
        / "sha256"
        / proposal.proposal_fingerprint[:2]
        / proposal.proposal_fingerprint
        / "manifest.json"
    )
    payload = json.loads(target.read_text())
    payload["search_space_fingerprint"] = "f" * 64
    target.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    with pytest.raises(OnlySymbolicSearchStoreError) as error:
        store.load_proposal_verified(proposal.proposal_fingerprint)
    assert error.value.code == "SEARCH_PROPOSAL_CORRUPT"


def test_candidate_output_cannot_be_an_indicator() -> None:
    generation, search_space = space()
    indicator = next(
        item
        for item in search_space.component_instances
        if item.type_reference.type_id.startswith("onlyalpha.indicator")
    )
    invalid = replace(
        search_space,
        candidate_output_contract=OnlySymbolicCandidateOutputContractV1(
            indicator.component_instance_fingerprint,
            "value",
        ),
    )
    with pytest.raises(Exception) as error:
        verify_symbolic_search_space(invalid, generation)
    assert getattr(error.value, "code", None) == "SEARCH_CANDIDATE_OUTPUT_INVALID"
