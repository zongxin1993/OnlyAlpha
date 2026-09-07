from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace

import pytest

from onlyalpha.calculation import (
    FACTOR_SCORE_SEMANTIC_TYPE,
    OnlyCalculationDataType,
    OnlyCalculationNodeDefinition,
    OnlyFactorKind,
    OnlyMissingValuePolicy,
    OnlyTimestampSemantic,
)
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition
from onlyalpha.research.calculation import (
    OnlyResearchDatasetSourceContractV1,
    only_research_dataset_source_contract,
)
from onlyalpha.research.experiment import (
    OnlySearchFailureCode,
    OnlySearchIterationDisposition,
    OnlySearchIterationResultV1,
    OnlySearchResearchResultReferenceV1,
)
from onlyalpha.research.search.symbolic import (
    OnlyJsonSymbolicSearchStore,
    OnlySymbolicCandidateOutputReferenceV1,
    OnlySymbolicGraphProposalV1,
    OnlySymbolicSearchError,
    OnlySymbolicSearchStoreError,
    enumerate_symbolic_factor_proposals,
    only_deterministic_enumeration_implementation,
    verify_symbolic_proposal_reconstruction,
)
from onlyalpha.research.specification.model import OnlyResearchSeriesSelector

from .support import space
from .test_research_and_provenance_integration import _evaluation, _verified_context


def test_evaluation_contract_identity_store_and_semantic_membership(tmp_path) -> None:
    evaluation = _evaluation("a" * 64)
    assert evaluation == type(evaluation).from_dict(evaluation.to_dict())
    assert _evaluation("a" * 64).evaluation_contract_fingerprint == evaluation.evaluation_contract_fingerprint
    assert _evaluation("b" * 64).evaluation_contract_fingerprint != evaluation.evaluation_contract_fingerprint

    statistic = evaluation.statistics[0]
    target_changed = replace(
        evaluation,
        statistics=(replace(statistic, target=replace(statistic.target, output_name="other")),),
    )
    feature_changed = replace(
        evaluation,
        statistics=(replace(statistic, feature=replace(statistic.feature, output_name="other")),),
    )
    evidence_changed = replace(
        evaluation,
        evidence=replace(
            evaluation.evidence,
            published_series=(
                OnlyResearchSeriesSelector(evaluation.candidate_calculation_id, "other", "factor_value"),
            ),
        ),
    )
    candidate_renamed = replace(
        evaluation,
        candidate_calculation_id="candidate2",
        statistics=(
            replace(
                statistic,
                feature=replace(statistic.feature, calculation_id="candidate2"),
            ),
        ),
        evidence=replace(
            evaluation.evidence,
            candidate_calculation_id="candidate2",
            published_series=tuple(
                replace(item, calculation_id="candidate2")
                if item.calculation_id == evaluation.candidate_calculation_id
                else item
                for item in evaluation.evidence.published_series
            ),
        ),
    )
    statistics_membership_changed = replace(
        evaluation,
        statistics=(statistic, replace(statistic, feature=replace(statistic.feature, output_name="other"))),
    )
    fixed_changed = replace(
        evaluation,
        fixed_calculations=(
            replace(
                evaluation.fixed_calculations[0],
                graph_template=replace(
                    evaluation.fixed_calculations[0].graph_template,
                    nodes=tuple(
                        replace(node, alias="changed") for node in evaluation.fixed_calculations[0].graph_template.nodes
                    ),
                ),
            ),
            *evaluation.fixed_calculations[1:],
        ),
    )
    identities = {
        item.evaluation_contract_fingerprint
        for item in (
            evaluation,
            target_changed,
            feature_changed,
            evidence_changed,
            candidate_renamed,
            statistics_membership_changed,
            fixed_changed,
        )
    }
    assert len(identities) == 7

    store = OnlyJsonSymbolicSearchStore(tmp_path)
    assert store.commit_evaluation_contract(evaluation).disposition.value == "CREATED"
    assert store.commit_evaluation_contract(evaluation).disposition.value == "REUSED"
    assert store.load_evaluation_contract_intrinsic_verified(evaluation.evaluation_contract_fingerprint) == evaluation
    manifest = (
        tmp_path
        / "research"
        / "symbolic-search"
        / "evaluations"
        / "sha256"
        / evaluation.evaluation_contract_fingerprint[:2]
        / evaluation.evaluation_contract_fingerprint
        / "manifest.json"
    )
    payload = json.loads(manifest.read_text())
    payload["dataset_snapshot_fingerprint"] = "f" * 64
    manifest.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    with pytest.raises(OnlySymbolicSearchStoreError, match="SEARCH_EVALUATION_CORRUPT"):
        store.load_evaluation_contract_intrinsic_verified(evaluation.evaluation_contract_fingerprint)


def test_dataset_source_contract_is_deterministic_and_terminal_persists_reference_only() -> None:
    contract = only_research_dataset_source_contract("bar.close")
    assert isinstance(contract, OnlyResearchDatasetSourceContractV1)
    assert contract.source_id == "bar.close"
    legacy_constructor = OnlyResearchDatasetSourceContractV1(
        "close",
        OnlyCalculationDataType.DECIMAL,
        frozenset({"NUMERIC_SERIES", "PRICE"}),
    )
    assert legacy_constructor == contract
    program = (
        "from onlyalpha.research.calculation import only_research_dataset_source_contract; "
        "print(only_research_dataset_source_contract('bar.close').source_contract_fingerprint)"
    )
    fresh = subprocess.check_output([sys.executable, "-c", program], text=True).strip()
    assert fresh == contract.source_contract_fingerprint
    assert replace(contract, data_type=OnlyCalculationDataType.INTEGER).source_contract_fingerprint != fresh
    assert replace(contract, semantic_roles=frozenset({"NUMERIC_SERIES"})).source_contract_fingerprint != fresh
    assert replace(contract, dimensions=("TIME", "INSTRUMENT")).source_contract_fingerprint != fresh
    assert replace(contract, unit="USD").source_contract_fingerprint != fresh

    _generation, search_space = space()
    terminal_payload = search_space.external_source_terminals[0].to_dict()
    assert set(terminal_payload) == {
        "schema_version",
        "source_id",
        "source_contract_fingerprint",
        "terminal_fingerprint",
    }
    assert not (
        {"data_type", "semantic_type", "semantic_roles", "dimensions", "unit", "nullable"} & set(terminal_payload)
    )


def test_experiment_v2_binds_evaluation_and_runtime_algorithm_exactly(tmp_path) -> None:
    generation, search_space = space(max_nodes=1)
    _store, experiment, context, resolver = _verified_context(tmp_path, generation, search_space, "a" * 64)
    reloaded = resolver.resolve_verified_context(experiment)
    assert reloaded.experiment == context.experiment
    assert reloaded.evaluation_contract == context.evaluation_contract
    assert reloaded.verified_search_space.search_space == context.verified_search_space.search_space
    changed_evaluation = _evaluation("b" * 64)
    assert changed_evaluation.evaluation_contract_fingerprint != (
        experiment.evaluation_context_reference.evaluation_fingerprint
    )
    changed_experiment = replace(
        experiment,
        evaluation_context_reference=replace(
            experiment.evaluation_context_reference,
            evaluation_fingerprint=changed_evaluation.evaluation_contract_fingerprint,
        ),
    )
    assert changed_experiment.experiment_fingerprint != experiment.experiment_fingerprint
    actual = only_deterministic_enumeration_implementation()
    assert experiment.search_algorithm_binding.implementation_fingerprint == actual.implementation_fingerprint
    assert experiment.search_algorithm_binding.source_revision == actual.source_revision

    wrong = replace(
        experiment,
        search_algorithm_binding=replace(
            experiment.search_algorithm_binding,
            implementation_fingerprint="f" * 64,
        ),
    )
    with pytest.raises(OnlySymbolicSearchError, match="SEARCH_ALGORITHM_IMPLEMENTATION_MISMATCH"):
        resolver.resolve_verified_context(wrong)


def test_context_fails_closed_on_source_evaluation_catalog_and_dataset_contradictions(tmp_path) -> None:
    generation, search_space = space(max_nodes=1)
    store, experiment, _context, resolver = _verified_context(tmp_path, generation, search_space, "a" * 64)

    wrong_source = replace(
        search_space,
        external_source_terminals=(
            replace(search_space.external_source_terminals[0], source_contract_fingerprint="f" * 64),
        ),
    )
    store.commit_search_space(wrong_source)
    wrong_source_experiment = replace(
        experiment,
        search_space_reference=replace(
            experiment.search_space_reference,
            search_space_fingerprint=wrong_source.search_space_fingerprint,
        ),
    )
    with pytest.raises(OnlySymbolicSearchError, match="SEARCH_SOURCE_CONTRACT_MISMATCH"):
        resolver.resolve_verified_context(wrong_source_experiment)

    wrong_evaluation = _evaluation("b" * 64)
    store.commit_evaluation_contract(wrong_evaluation)
    wrong_evaluation_experiment = replace(
        experiment,
        evaluation_context_reference=replace(
            experiment.evaluation_context_reference,
            evaluation_fingerprint=wrong_evaluation.evaluation_contract_fingerprint,
        ),
    )
    with pytest.raises(OnlySymbolicSearchError, match="SEARCH_EVALUATION_DATASET_MISMATCH"):
        resolver.resolve_verified_context(wrong_evaluation_experiment)

    with pytest.raises(OnlySymbolicSearchError, match="SEARCH_CATALOG_REFERENCE_INVALID"):
        resolver.resolve_verified_context(replace(experiment, catalog_generation_fingerprint="e" * 64))
    with pytest.raises(OnlySymbolicSearchError, match="SEARCH_DATASET_REFERENCE_INVALID"):
        resolver.resolve_verified_context(replace(experiment, dataset_snapshot_fingerprint="d" * 64))


def _forged_proposal(proposal: OnlySymbolicGraphProposalV1, field_name: str) -> OnlySymbolicGraphProposalV1:
    node = proposal.graph.nodes[0]
    definition = node.definition
    if field_name == "inputs":
        forged = replace(
            definition, inputs=(replace(definition.inputs[0], semantic_type="FORGED"), *definition.inputs[1:])
        )
    elif field_name == "input_bindings":
        first_name = definition.inputs[0].name
        first = definition.input_bindings[first_name]
        forged = replace(
            definition,
            input_bindings={
                **definition.input_bindings,
                first_name: replace(first, source="bar.unknown"),
            },
        )
    elif field_name == "outputs":
        forged = replace(
            definition, outputs=(replace(definition.outputs[0], data_type=OnlyCalculationDataType.INTEGER),)
        )
    elif field_name == "semantic_type":
        forged = replace(
            definition, outputs=(replace(definition.outputs[0], semantic_type=FACTOR_SCORE_SEMANTIC_TYPE),)
        )
    elif field_name == "warmup":
        forged = replace(definition, warmup=replace(definition.warmup, minimum_observations=9))
    elif field_name == "missing_values":
        alternative = next(item for item in OnlyMissingValuePolicy if item is not definition.missing_values)
        forged = replace(definition, missing_values=alternative)
    elif field_name == "timestamp":
        alternative = next(item for item in OnlyTimestampSemantic if item is not definition.timestamp)
        forged = replace(definition, timestamp=alternative)
    elif field_name == "numeric":
        forged = replace(definition, numeric=replace(definition.numeric, precision=definition.numeric.precision + 1))
    elif field_name == "factor_kind":
        alternative = next(item for item in OnlyFactorKind if item is not definition.factor_kind)
        forged = replace(definition, factor_kind=alternative)
    elif field_name == "extensions":
        forged = replace(definition, extensions={"forged": 1})
    else:  # pragma: no cover - fixed parametrization
        raise AssertionError(field_name)
    graph = OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(forged),))
    return OnlySymbolicGraphProposalV1(
        proposal.search_space_fingerprint,
        graph,
        OnlySymbolicCandidateOutputReferenceV1(
            graph.nodes[0].fingerprint, proposal.candidate_output_reference.output_name
        ),
    )


@pytest.mark.parametrize(
    "field_name",
    (
        "inputs",
        "input_bindings",
        "outputs",
        "semantic_type",
        "warmup",
        "missing_values",
        "timestamp",
        "numeric",
        "factor_kind",
        "extensions",
    ),
)
def test_proposal_reconstruction_rejects_descriptor_preserving_semantic_forgery(tmp_path, field_name: str) -> None:
    generation, search_space = space(max_nodes=1)
    _store, _experiment_value, context, _resolver = _verified_context(tmp_path, generation, search_space, "a" * 64)
    proposal = enumerate_symbolic_factor_proposals(context.verified_search_space, proposal_limit=1).proposals[0]
    forged = _forged_proposal(proposal, field_name)
    with pytest.raises(OnlySymbolicSearchError):
        verify_symbolic_proposal_reconstruction(forged, context)


def test_qualification_attempt_state_machine_is_exact() -> None:
    common = {
        "iteration_plan_fingerprint": "1" * 64,
        "candidate_fingerprint": "2" * 64,
        "research_attempted": True,
        "research_result_reference": None,
        "qualification_attempted": False,
        "qualification_decision_fingerprint": None,
        "disposition": OnlySearchIterationDisposition.FAILED,
        "failure_code": OnlySearchFailureCode.RESEARCH_EXECUTION_FAILED,
    }
    assert OnlySearchIterationResultV1(**common).research_attempted
    with pytest.raises(ValueError, match="QUALIFICATION_NOT_ATTEMPTED"):
        OnlySearchIterationResultV1(
            "1" * 64,
            "2" * 64,
            True,
            OnlySearchResearchResultReferenceV1("3" * 64, "4" * 64),
            True,
            None,
            OnlySearchIterationDisposition.FAILED,
            OnlySearchFailureCode.QUALIFICATION_NOT_ATTEMPTED,
        )


def test_exhaustion_boundary_distinguishes_less_equal_and_greater(tmp_path) -> None:
    generation, search_space = space(max_nodes=2)
    _store, _experiment_value, context, _resolver = _verified_context(tmp_path, generation, search_space, "a" * 64)
    all_proposals = enumerate_symbolic_factor_proposals(context.verified_search_space, proposal_limit=10_000)
    total = len(all_proposals.proposals)
    assert total > 1
    less = enumerate_symbolic_factor_proposals(context.verified_search_space, proposal_limit=total - 1)
    equal = enumerate_symbolic_factor_proposals(context.verified_search_space, proposal_limit=total)
    greater = enumerate_symbolic_factor_proposals(context.verified_search_space, proposal_limit=total + 1)
    assert (less.search_space_exhausted, less.proposal_limit_reached) == (False, True)
    assert (equal.search_space_exhausted, equal.proposal_limit_reached) == (True, True)
    assert (greater.search_space_exhausted, greater.proposal_limit_reached) == (True, False)
