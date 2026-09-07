from __future__ import annotations

import json
from dataclasses import replace

import pytest

from onlyalpha.calculation import (
    PREDICATE_OPERAND_SEMANTIC_TYPE,
    OnlyCalculationBackendKind,
    OnlyCalculationDataType,
    OnlyCalculationKind,
    OnlyCalculationTypeReference,
    OnlyInputDefinition,
)
from onlyalpha.calculation.registry import OnlyCalculationBackendRegistration, OnlyCalculationRegistry
from onlyalpha.quant_assets import OnlyQuantAssetCatalogManager
from onlyalpha.research.calculation import (
    OnlyResearchCalculationError,
    OnlyResearchDatasetSourceContractV1,
    only_research_dataset_source_contract,
    only_research_dataset_source_output,
)
from onlyalpha.research.experiment import (
    OnlyJsonSearchProvenanceStore,
    OnlySearchIterationPlanV1,
    OnlySearchProvenanceError,
)
from onlyalpha.research.search.symbolic import (
    SYMBOLIC_PROPOSAL_KIND,
    SYMBOLIC_PROPOSAL_SCHEMA_VERSION,
    OnlyJsonSymbolicSearchStore,
    OnlySymbolicSearchContextResolver,
    OnlySymbolicSearchError,
    OnlySymbolicSearchStoreError,
    admit_current_symbolic_algorithm_runtime,
    enumerate_symbolic_factor_proposals,
    only_deterministic_enumeration_implementation,
)
from onlyalpha.research.specification.model import OnlyResearchSeriesSelector
from tests.research.specification.support import registry as specification_registry
from tests.research.sweep.support import factor_template

from .support import space
from .test_research_and_provenance_integration import _Datasets, _evaluation, _verified_context


def _plan(experiment, proposal, index: int, **changes):  # type: ignore[no-untyped-def]
    values = {
        "experiment_fingerprint": experiment.experiment_fingerprint,
        "iteration_index": index,
        "proposal_kind": SYMBOLIC_PROPOSAL_KIND,
        "proposal_schema_version": SYMBOLIC_PROPOSAL_SCHEMA_VERSION,
        "proposal_fingerprint": proposal.proposal_fingerprint,
        "decision_input_context_fingerprints": (),
        "decision_tool_result_fingerprints": (),
        "decision_output_fingerprint": proposal.proposal_fingerprint,
    }
    values.update(changes)
    return OnlySearchIterationPlanV1(**values)


def test_algorithm_manifest_store_is_put_once_canonical_and_corruption_closed(tmp_path) -> None:
    manifest = only_deterministic_enumeration_implementation()
    assert manifest.source_revision != "source-tree"
    assert manifest == type(manifest).from_dict(manifest.to_dict())
    assert tuple(item.logical_resource_id for item in manifest.resources) == tuple(
        sorted(item.logical_resource_id for item in manifest.resources)
    )
    store = OnlyJsonSymbolicSearchStore(tmp_path)
    assert store.commit_algorithm_implementation_manifest(manifest).disposition.value == "CREATED"
    assert store.commit_algorithm_implementation_manifest(manifest).disposition.value == "REUSED"
    assert (
        store.load_algorithm_implementation_manifest_intrinsic_verified(manifest.implementation_fingerprint) == manifest
    )
    path = (
        tmp_path
        / "research"
        / "symbolic-search"
        / "algorithm-manifests"
        / "sha256"
        / manifest.implementation_fingerprint[:2]
        / manifest.implementation_fingerprint
        / "manifest.json"
    )
    payload = json.loads(path.read_text())
    payload["source_revision"] = "forged"
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    with pytest.raises(OnlySymbolicSearchStoreError, match="SEARCH_ALGORITHM_MANIFEST_CORRUPT"):
        store.load_algorithm_implementation_manifest_intrinsic_verified(manifest.implementation_fingerprint)


def test_historical_manifest_read_is_separate_from_runtime_admission(tmp_path) -> None:
    generation, search_space = space(max_nodes=2)
    store, experiment, context, resolver = _verified_context(tmp_path, generation, search_space, "a" * 64)
    historical = store.load_algorithm_implementation_manifest_intrinsic_verified(
        experiment.search_algorithm_binding.implementation_fingerprint
    )
    changed_resource = replace(historical.resources[0], byte_sha256="f" * 64)
    runtime_b = replace(historical, resources=(changed_resource, *historical.resources[1:]))
    historical_context = resolver.resolve_verified_context(experiment)
    assert historical_context.historical_algorithm_manifest == historical
    assert (
        admit_current_symbolic_algorithm_runtime(historical_context, historical).runtime_algorithm_manifest
        == historical
    )
    with pytest.raises(OnlySymbolicSearchError, match="SEARCH_ALGORITHM_RUNTIME_MISMATCH"):
        admit_current_symbolic_algorithm_runtime(historical_context, runtime_b)
    upgraded_resolver = OnlySymbolicSearchContextResolver(
        symbolic_store=store,
        catalogs=OnlyQuantAssetCatalogManager(generation),
        datasets=_Datasets("a" * 64),
        research_calculation_registry=specification_registry(),
        algorithm_implementation=runtime_b,
    )
    upgraded_historical = upgraded_resolver.resolve_verified_context(experiment)
    assert upgraded_historical.historical_algorithm_manifest == historical
    with pytest.raises(OnlySymbolicSearchError, match="SEARCH_ALGORITHM_RUNTIME_MISMATCH"):
        upgraded_resolver.admit_current_runtime(upgraded_historical)


@pytest.mark.parametrize(
    ("index", "proposal_index", "changes", "code"),
    (
        (0, 0, {}, None),
        (0, 1, {}, "SEARCH_OCCURRENCE_PROPOSAL_MISMATCH"),
        (1, 0, {}, "SEARCH_OCCURRENCE_PROPOSAL_MISMATCH"),
        (0, 0, {"parent_iteration_result_fingerprint": "1" * 64}, "SEARCH_OCCURRENCE_PARENT_FORBIDDEN"),
        (0, 0, {"decision_input_context_fingerprints": ("2" * 64,)}, "SEARCH_OCCURRENCE_DECISION_CONTEXT_FORBIDDEN"),
        (0, 0, {"decision_tool_result_fingerprints": ("3" * 64,)}, "SEARCH_OCCURRENCE_TOOL_CONTEXT_FORBIDDEN"),
        (0, 0, {"decision_output_fingerprint": "4" * 64}, "SEARCH_OCCURRENCE_DECISION_OUTPUT_MISMATCH"),
    ),
)
def test_exact_deterministic_occurrence_mapping(tmp_path, index, proposal_index, changes, code) -> None:  # type: ignore[no-untyped-def]
    generation, search_space = space(max_nodes=2)
    store, experiment, context, resolver = _verified_context(tmp_path, generation, search_space, "a" * 64)
    proposals = enumerate_symbolic_factor_proposals(
        context.verified_search_space, proposal_limit=experiment.search_budget.proposal_limit
    ).proposals
    assert len(proposals) >= 2
    proposal = proposals[proposal_index]
    store.commit_proposal(proposal)
    plan = _plan(experiment, proposal, index, **changes)
    if code is None:
        assert resolver.load_proposal_occurrence_contextual_verified(experiment, plan).proposal == proposal
    else:
        with pytest.raises(OnlySymbolicSearchError, match=code):
            resolver.load_proposal_occurrence_contextual_verified(experiment, plan)


@pytest.mark.parametrize("offset", (0, 2))
def test_occurrence_at_or_beyond_budget_fails_even_for_legal_proposal(tmp_path, offset: int) -> None:
    generation, search_space = space(max_nodes=2)
    store, experiment, context, resolver = _verified_context(tmp_path, generation, search_space, "a" * 64)
    proposal = enumerate_symbolic_factor_proposals(context.verified_search_space, proposal_limit=1).proposals[0]
    store.commit_proposal(proposal)
    plan = _plan(experiment, proposal, experiment.search_budget.proposal_limit + offset)
    with pytest.raises(OnlySymbolicSearchError, match="SEARCH_OCCURRENCE_OUTSIDE_BUDGET"):
        resolver.load_proposal_occurrence_contextual_verified(experiment, plan)


def test_legal_proposal_outside_exact_budget_prefix_cannot_be_substituted(tmp_path) -> None:
    generation, search_space = space(max_nodes=3)
    store, experiment, context, resolver = _verified_context(tmp_path, generation, search_space, "a" * 64)
    proposals = enumerate_symbolic_factor_proposals(
        context.verified_search_space,
        proposal_limit=experiment.search_budget.proposal_limit + 1,
    ).proposals
    assert len(proposals) > experiment.search_budget.proposal_limit
    outside = proposals[experiment.search_budget.proposal_limit]
    store.commit_proposal(outside)
    with pytest.raises(OnlySymbolicSearchError, match="SEARCH_OCCURRENCE_PROPOSAL_MISMATCH"):
        resolver.load_proposal_occurrence_contextual_verified(experiment, _plan(experiment, outside, 0))


def test_b31_context_adapter_rejects_swapped_ordinal_occurrence(tmp_path) -> None:
    generation, search_space = space(max_nodes=2)
    store, experiment, context, resolver = _verified_context(tmp_path, generation, search_space, "a" * 64)
    provenance = OnlyJsonSearchProvenanceStore(
        tmp_path,
        catalogs=OnlyQuantAssetCatalogManager(generation),
        datasets=_Datasets("a" * 64),
        search_contexts=resolver,
    )
    provenance.commit_experiment(experiment)
    proposals = enumerate_symbolic_factor_proposals(context.verified_search_space, proposal_limit=2).proposals
    store.commit_proposal(proposals[1])
    with pytest.raises(OnlySearchProvenanceError, match="SEARCH_PROPOSAL_REFERENCE_INVALID"):
        provenance.commit_iteration_plan(_plan(experiment, proposals[1], 0))


@pytest.mark.parametrize(
    ("source_id", "semantic_type", "passes"),
    (
        ("bar.close", "NUMERIC_SERIES", True),
        ("bar.close", "PRICE", True),
        ("bar.close", "QUANTITY", False),
        ("bar.volume", "NUMERIC_SERIES", True),
        ("bar.volume", "QUANTITY", True),
    ),
)
def test_dataset_source_preserves_all_semantic_roles(source_id: str, semantic_type: str, passes: bool) -> None:
    contract = only_research_dataset_source_contract(source_id)
    assert contract is not None
    expected = OnlyInputDefinition("value", OnlyCalculationDataType.DECIMAL, True, ("TIME",), semantic_type, None)
    if passes:
        assert only_research_dataset_source_output(contract, expected, nullable=False).semantic_type == semantic_type
    else:
        with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_INPUT_INCOMPATIBLE"):
            only_research_dataset_source_output(contract, expected, nullable=False)
    predicate = replace(expected, semantic_type=PREDICATE_OPERAND_SEMANTIC_TYPE)
    only_research_dataset_source_output(contract, predicate, nullable=False)


def test_dataset_source_role_order_does_not_change_identity() -> None:
    contract = only_research_dataset_source_contract("bar.close")
    assert contract is not None
    reordered = OnlyResearchDatasetSourceContractV1(
        contract.column,
        contract.data_type,
        frozenset(reversed(sorted(contract.semantic_roles))),
        contract.dimensions,
        contract.unit,
        contract.source_id,
    )
    assert reordered.source_contract_fingerprint == contract.source_contract_fingerprint


def test_evaluation_fixed_semantics_close_through_normal_research_authority(tmp_path) -> None:
    generation, search_space = space(max_nodes=1)
    store, experiment, context, resolver = _verified_context(tmp_path, generation, search_space, "a" * 64)
    assert context.verified_evaluation.witness_resolution.workload.statistics_plans
    evaluation = _evaluation("a" * 64)
    fixed = evaluation.fixed_calculations[0]
    node = fixed.graph_template.nodes[0]
    statistic = evaluation.statistics[0]

    def changed_node(**changes):  # type: ignore[no-untyped-def]
        return replace(
            evaluation,
            fixed_calculations=(
                replace(fixed, graph_template=replace(fixed.graph_template, nodes=(replace(node, **changes),))),
            ),
        )

    cases = {
        "unknown_type": changed_node(
            type_reference=OnlyCalculationTypeReference(OnlyCalculationKind.TARGET, "onlyalpha.target.unknown", "1")
        ),
        "wrong_semantic_version": changed_node(type_reference=replace(node.type_reference, semantic_version="999")),
        "invalid_parameters": changed_node(parameters={"exit_offset": "invalid"}),
        "illegal_graph_binding": changed_node(
            input_bindings=(replace(node.input_bindings[0], input_name="unknown_input"), *node.input_bindings[1:])
        ),
        "missing_target_output": replace(
            evaluation,
            statistics=(replace(statistic, target=replace(statistic.target, output_name="missing")),),
        ),
        "non_target_target_semantics": replace(
            evaluation,
            fixed_calculations=(
                *evaluation.fixed_calculations,
                replace(fixed, calculation_id="not_target", graph_template=factor_template()),
            ),
            statistics=(
                replace(
                    statistic,
                    target=OnlyResearchSeriesSelector("not_target", "momentum", "factor_value"),
                ),
            ),
        ),
        "invalid_fixed_statistics_selector": replace(
            evaluation,
            statistics=(
                statistic,
                replace(
                    statistic,
                    feature=OnlyResearchSeriesSelector("target", "forward_return", "target_value"),
                ),
            ),
        ),
        "invalid_fixed_evidence_selector": replace(
            evaluation,
            evidence=replace(
                evaluation.evidence,
                published_series=(
                    *evaluation.evidence.published_series,
                    OnlyResearchSeriesSelector("target", "forward_return", "missing"),
                ),
            ),
        ),
        "invalid_fixed_signal_selector": replace(
            evaluation,
            evidence=replace(
                evaluation.evidence,
                signals=replace(
                    evaluation.evidence.signals,
                    eligibility=OnlyResearchSeriesSelector("target", "forward_return", "target_value"),
                ),
            ),
        ),
    }
    for _name, invalid in cases.items():
        store.commit_evaluation_contract(invalid)
        changed_experiment = replace(
            experiment,
            evaluation_context_reference=replace(
                experiment.evaluation_context_reference,
                evaluation_fingerprint=invalid.evaluation_contract_fingerprint,
            ),
        )
        with pytest.raises(OnlySymbolicSearchError, match="SEARCH_EVALUATION_CONTEXT_INVALID"):
            resolver.resolve_verified_context(changed_experiment)


def test_evaluation_exact_type_without_research_backend_fails_closed(tmp_path) -> None:
    generation, search_space = space(max_nodes=1)
    store, experiment, _context, _resolver = _verified_context(tmp_path, generation, search_space, "a" * 64)
    registry = OnlyCalculationRegistry()
    target_registration = None
    for registration in specification_registry().backend_registrations():
        if registration.type_definition.kind is OnlyCalculationKind.TARGET:
            target_registration = registration
            continue
        registry.register(registration)
    assert target_registration is not None
    registry.register(
        OnlyCalculationBackendRegistration(
            target_registration.type_definition,
            OnlyCalculationBackendKind.TRADING,
            target_registration.provider,
            target_registration.definition_resolver,
        )
    )
    historical_reader = OnlySymbolicSearchContextResolver(
        symbolic_store=store,
        catalogs=OnlyQuantAssetCatalogManager(generation),
        datasets=_Datasets("a" * 64),
        research_calculation_registry=registry,
    )
    with pytest.raises(OnlySymbolicSearchError, match="SEARCH_EVALUATION_CONTEXT_INVALID"):
        historical_reader.resolve_verified_context(experiment)
