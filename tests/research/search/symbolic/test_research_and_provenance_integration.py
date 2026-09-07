from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from onlyalpha_plugin_targets.registration import registrations as target_registrations

from onlyalpha.backtest import OnlyBacktestEvidenceStore
from onlyalpha.calculation import OnlyCalculationRegistry
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngineConfig
from onlyalpha.engine.engine import OnlyEngine
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.quant_assets import OnlyQuantAssetCatalogManager
from onlyalpha.research import (
    OnlyJsonResearchResultStore,
    OnlyParquetResearchCalculationResultStore,
    OnlyParquetResearchDatasetSnapshotStore,
    OnlyParquetResearchStatisticsResultStore,
)
from onlyalpha.research.experiment import (
    OnlyJsonSearchProvenanceStore,
    OnlySearchAlgorithmBindingV1,
    OnlySearchBudgetV1,
    OnlySearchDecisionEngineBindingV1,
    OnlySearchDecisionMode,
    OnlySearchEvaluationContextReferenceV1,
    OnlySearchExperimentManifestV2,
    OnlySearchHypothesisV1,
    OnlySearchIterationDisposition,
    OnlySearchIterationPlanV1,
    OnlySearchIterationResultV1,
    OnlySearchProvenanceError,
    OnlySearchRandomnessMode,
    OnlySearchResearchResultReferenceV1,
    OnlySearchSpaceReferenceV1,
    OnlySearchWorkflowBindingV1,
)
from onlyalpha.research.search.symbolic import (
    DETERMINISTIC_ENUMERATION_ALGORITHM_ID,
    DETERMINISTIC_ENUMERATION_ALGORITHM_SEMANTIC_VERSION,
    SYMBOLIC_EVALUATION_CONTRACT_KIND,
    SYMBOLIC_EVALUATION_CONTRACT_SCHEMA_VERSION,
    SYMBOLIC_PROPOSAL_KIND,
    SYMBOLIC_PROPOSAL_SCHEMA_VERSION,
    SYMBOLIC_SEARCH_SPACE_CONTEXT_SCHEMA_VERSION,
    SYMBOLIC_SEARCH_SPACE_KIND,
    OnlyJsonSymbolicSearchStore,
    OnlySymbolicResearchEvaluationContractV1,
    OnlySymbolicSearchContextResolver,
    OnlySymbolicSearchError,
    enumerate_symbolic_factor_proposals,
    only_deterministic_enumeration_implementation,
    resolve_symbolic_research_candidate,
    run_symbolic_search_workflow,
    verify_symbolic_proposal_reconstruction,
)
from onlyalpha.research.specification.identity import only_research_candidate_fingerprint
from onlyalpha.research.specification.model import (
    OnlyResearchScientificEvidenceSpec,
    OnlyResearchSeriesSelector,
    OnlyResearchSignalEvidenceSpec,
    OnlyResearchSpecification,
)
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver
from onlyalpha.runtime.result import OnlyRuntimeResultStatus
from onlyalpha.strategy.freeze_relation import OnlyStrategyFreezeRelation
from onlyalpha.strategy.qualification import (
    OnlyQualificationCriterion,
    OnlyQualificationEvaluator,
    OnlyQualificationEvidenceKind,
    OnlyQualificationEvidenceReference,
    OnlyQualificationGate,
    OnlyQualificationOutcome,
    OnlyQualificationPolicyRevision,
)
from onlyalpha.strategy.qualification_store import (
    OnlyQualificationPolicyStore,
    _only_compose_qualification_decision_authority,
)
from onlyalpha.strategy.store import (
    OnlyFrozenStrategyRevisionStore,
    _only_authorize_frozen_strategy_publication,
    _only_compose_frozen_strategy_authority,
)
from tests.research.calculation.support import snapshot
from tests.research.specification.support import registry as specification_registry
from tests.research.specification.support import specification
from tests.strategy.p9_support import p9_strategy_case

from .support import space, verified_dataset


class _Datasets:
    def __init__(self, fingerprint: str) -> None:
        self.value = verified_dataset(fingerprint)

    def load_verified_table(self, fingerprint: str) -> object:
        if fingerprint != self.value.snapshot.snapshot_fingerprint:
            raise KeyError(fingerprint)
        return self.value


def _experiment(
    search_space_fingerprint: str,
    catalog_fingerprint: str,
    dataset_fingerprint: str,
    evaluation_fingerprint: str,
):
    algorithm = only_deterministic_enumeration_implementation()
    return OnlySearchExperimentManifestV2(
        OnlySearchHypothesisV1("A fixed admitted momentum bridge can compose exact reusable calculations."),
        OnlySearchAlgorithmBindingV1(
            DETERMINISTIC_ENUMERATION_ALGORITHM_ID,
            DETERMINISTIC_ENUMERATION_ALGORITHM_SEMANTIC_VERSION,
            algorithm.implementation_fingerprint,
            algorithm.source_revision,
        ),
        OnlySearchSpaceReferenceV1(
            SYMBOLIC_SEARCH_SPACE_KIND,
            SYMBOLIC_SEARCH_SPACE_CONTEXT_SCHEMA_VERSION,
            search_space_fingerprint,
        ),
        OnlySearchEvaluationContextReferenceV1(
            SYMBOLIC_EVALUATION_CONTRACT_KIND,
            SYMBOLIC_EVALUATION_CONTRACT_SCHEMA_VERSION,
            evaluation_fingerprint,
        ),
        OnlySearchRandomnessMode.NONE,
        None,
        OnlySearchBudgetV1(3, 2, 1),
        catalog_fingerprint,
        dataset_fingerprint,
        OnlySearchWorkflowBindingV1("symbolic.factor.search", "1"),
        OnlySearchDecisionEngineBindingV1(OnlySearchDecisionMode.DETERMINISTIC),
    )


def _evaluation(dataset: str) -> OnlySymbolicResearchEvaluationContractV1:
    return OnlySymbolicResearchEvaluationContractV1.from_specification(_scientific_template(dataset), "feature")


def _verified_context(
    root: Path,
    generation,  # type: ignore[no-untyped-def]
    search_space,  # type: ignore[no-untyped-def]
    dataset: str,
):
    symbolic = OnlyJsonSymbolicSearchStore(root)
    evaluation = _evaluation(dataset)
    symbolic.commit_search_space(search_space)
    symbolic.commit_evaluation_contract(evaluation)
    symbolic.commit_algorithm_implementation_manifest(only_deterministic_enumeration_implementation())
    experiment = _experiment(
        search_space.search_space_fingerprint,
        generation.generation_fingerprint,
        dataset,
        evaluation.evaluation_contract_fingerprint,
    )
    context_resolver = OnlySymbolicSearchContextResolver(
        symbolic_store=symbolic,
        catalogs=OnlyQuantAssetCatalogManager(generation),
        datasets=_Datasets(dataset),
        research_calculation_registry=specification_registry(),
    )
    return symbolic, experiment, context_resolver.resolve_verified_context(experiment), context_resolver


def _scientific_template(dataset: str) -> OnlyResearchSpecification:
    base = specification(dataset)
    return OnlyResearchSpecification(
        base.dataset_snapshot_fingerprint,
        base.calculations,
        base.statistics,
        OnlyResearchScientificEvidenceSpec(
            "feature",
            (OnlyResearchSeriesSelector("feature", "momentum", "factor_value"),),
            OnlyResearchSignalEvidenceSpec(),
        ),
        2,
    )


def test_b31_search_space_and_proposal_references_exact_load(tmp_path) -> None:
    generation, search_space = space(max_nodes=1)
    dataset = "a" * 64
    symbolic, experiment, context, context_resolver = _verified_context(tmp_path, generation, search_space, dataset)
    provenance = OnlyJsonSearchProvenanceStore(
        tmp_path,
        catalogs=OnlyQuantAssetCatalogManager(generation),
        datasets=_Datasets(dataset),
        search_contexts=context_resolver,
    )
    provenance.commit_experiment(experiment)
    proposal = enumerate_symbolic_factor_proposals(context.verified_search_space, proposal_limit=1).proposals[0]
    symbolic.commit_proposal(proposal)
    plan = OnlySearchIterationPlanV1(
        experiment.experiment_fingerprint,
        0,
        SYMBOLIC_PROPOSAL_KIND,
        SYMBOLIC_PROPOSAL_SCHEMA_VERSION,
        proposal.proposal_fingerprint,
        (),
        (),
        proposal.proposal_fingerprint,
    )
    provenance.commit_iteration_plan(plan)
    assert provenance.load_experiment_verified(experiment.experiment_fingerprint) == experiment
    assert provenance.load_iteration_plan_verified(plan.iteration_plan_fingerprint) == plan


def test_b31_missing_symbolic_authority_fails_closed(tmp_path) -> None:
    generation, search_space = space(max_nodes=1)
    dataset = "a" * 64
    evaluation = _evaluation(dataset)
    experiment = _experiment(
        search_space.search_space_fingerprint,
        generation.generation_fingerprint,
        dataset,
        evaluation.evaluation_contract_fingerprint,
    )
    provenance = OnlyJsonSearchProvenanceStore(
        tmp_path,
        catalogs=OnlyQuantAssetCatalogManager(generation),
        datasets=_Datasets(dataset),
    )
    with pytest.raises(OnlySearchProvenanceError) as error:
        provenance.commit_experiment(experiment)
    assert error.value.code == "SEARCH_EXTERNAL_REFERENCE_READER_UNAVAILABLE"


def test_proposal_uses_normal_resolver_candidate_identity_and_fixed_template(tmp_path) -> None:
    generation, search_space = space(max_nodes=1)
    symbolic, _experiment_value, context, _context_resolver = _verified_context(
        tmp_path, generation, search_space, "a" * 64
    )
    proposal = enumerate_symbolic_factor_proposals(context.verified_search_space, proposal_limit=1).proposals[0]
    symbolic.commit_proposal(proposal)
    verified_proposal = verify_symbolic_proposal_reconstruction(proposal, context)
    registry = generation.calculation_registry()
    assert isinstance(registry, OnlyCalculationRegistry)
    for registration in target_registrations():
        registry.register(registration)
    resolved = resolve_symbolic_research_candidate(
        verified_proposal,
        OnlyResearchSpecificationResolver(registry),
    )
    candidate = resolved.candidate
    assert candidate.candidate_fingerprint == only_research_candidate_fingerprint(
        resolved.resolution.specification_fingerprint,
        "feature",
        candidate.assignment,
        candidate.calculation_fingerprint,
    )
    assert candidate.candidate_fingerprint not in {proposal.proposal_fingerprint, proposal.graph_fingerprint}
    assert candidate.graph_fingerprint == proposal.graph_fingerprint
    assert resolved.resolution.workload.statistics_plans


def test_valid_proposal_executes_through_normal_research_runtime_and_immutable_result(tmp_path) -> None:
    layout = OnlyUserDataLayout(tmp_path)
    datasets = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    candidate_dataset, partitions = snapshot()
    dataset = datasets.commit(candidate_dataset, partitions)
    generation, search_space = space(max_nodes=1)
    symbolic = OnlyJsonSymbolicSearchStore(tmp_path)
    evaluation = _evaluation(dataset.snapshot_fingerprint)
    symbolic.commit_search_space(search_space)
    symbolic.commit_evaluation_contract(evaluation)
    symbolic.commit_algorithm_implementation_manifest(only_deterministic_enumeration_implementation())
    experiment = _experiment(
        search_space.search_space_fingerprint,
        generation.generation_fingerprint,
        dataset.snapshot_fingerprint,
        evaluation.evaluation_contract_fingerprint,
    )
    context = OnlySymbolicSearchContextResolver(
        symbolic_store=symbolic,
        catalogs=OnlyQuantAssetCatalogManager(generation),
        datasets=datasets,
        research_calculation_registry=specification_registry(),
    ).resolve_verified_context(experiment)
    proposal = enumerate_symbolic_factor_proposals(context.verified_search_space, proposal_limit=1).proposals[0]
    verified_proposal = verify_symbolic_proposal_reconstruction(proposal, context)
    registry = generation.calculation_registry()
    for registration in target_registrations():
        registry.register(registration)
    resolved = resolve_symbolic_research_candidate(
        verified_proposal,
        OnlyResearchSpecificationResolver(registry),
    )

    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("symbolic-research"), tmp_path))
    runtime_id = engine.add_research_workload(resolved.resolution.workload)
    engine.initialize()
    engine.start()
    outcome = engine.run_runtime(runtime_id)
    engine.stop()
    assert outcome.status is OnlyRuntimeResultStatus.COMPLETED
    assert outcome.research_result_fingerprint is not None

    calculations = OnlyParquetResearchCalculationResultStore(
        layout.research_calculation_result_root,
        datasets,
    )
    statistics = OnlyParquetResearchStatisticsResultStore(
        layout.research_statistics_result_root,
        calculations,
    )
    results = OnlyJsonResearchResultStore(layout.research_result_root, statistics, calculations)
    loaded = results.load_verified(resolved.resolution.workload.result_plan.fingerprint)
    candidate_fingerprint = resolved.candidate.candidate_fingerprint
    assert candidate_fingerprint is not None
    assert loaded.manifest.research_result_fingerprint == outcome.research_result_fingerprint
    assert [item.candidate_fingerprint for item in loaded.manifest.plan.candidates] == [candidate_fingerprint]


class _CollectingProvenance:
    def __init__(self) -> None:
        self.plans = []
        self.results = []

    def commit_iteration_plan(self, value):  # type: ignore[no-untyped-def]
        self.plans.append(value)

    def commit_iteration_result(self, value):  # type: ignore[no-untyped-def]
        self.results.append(value)


class _FakeResearch:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, resolution, candidate):  # type: ignore[no-untyped-def]
        del resolution
        self.calls += 1
        assert candidate.candidate_fingerprint is not None
        return OnlySearchResearchResultReferenceV1("c" * 64, "d" * 64)


class _FakeQualification:
    def __init__(self, decision: str) -> None:
        self.decision = decision
        self.calls = 0

    def evaluate(self, candidate, research_result):  # type: ignore[no-untyped-def]
        del candidate, research_result
        self.calls += 1
        return self.decision


def test_workflow_enforces_separate_budgets_and_downstream_outcomes_are_non_adaptive(tmp_path) -> None:
    generation, search_space = space(max_nodes=2)
    _symbolic, _experiment_value, context, _context_resolver = _verified_context(
        tmp_path / "context", generation, search_space, "a" * 64
    )
    registry = generation.calculation_registry()
    for registration in target_registrations():
        registry.register(registration)
    resolver = OnlyResearchSpecificationResolver(registry)

    sequences = []
    for name, decision in (("pass", "e" * 64), ("fail", "f" * 64)):
        provenance = _CollectingProvenance()
        research = _FakeResearch()
        qualification = _FakeQualification(decision)
        outcome = run_symbolic_search_workflow(
            context=context,
            symbolic_store=OnlyJsonSymbolicSearchStore(tmp_path / name),
            provenance=provenance,
            resolver=resolver,
            research_executor=research,
            qualification_executor=qualification,
        )
        sequences.append([item.proposal_fingerprint for item in outcome.enumeration.proposals])
        assert research.calls == 2
        assert qualification.calls == 1
        assert len(outcome.iteration_plans) == 3
        assert len(outcome.iteration_results) == 3
    assert sequences[0] == sequences[1]


def test_workflow_rejects_mismatched_algorithm_and_randomness_bindings(tmp_path) -> None:
    generation, search_space = space(max_nodes=1)
    symbolic, experiment, _context, _context_resolver = _verified_context(tmp_path, generation, search_space, "a" * 64)
    registry = generation.calculation_registry()
    for registration in target_registrations():
        registry.register(registration)
    context_resolver = OnlySymbolicSearchContextResolver(
        symbolic_store=symbolic,
        catalogs=OnlyQuantAssetCatalogManager(generation),
        datasets=_Datasets("a" * 64),
        research_calculation_registry=specification_registry(),
    )

    wrong_algorithm = replace(
        experiment,
        search_algorithm_binding=replace(experiment.search_algorithm_binding, algorithm_semantic_version="2"),
    )
    with pytest.raises(OnlySymbolicSearchError) as algorithm_error:
        context_resolver.resolve_verified_context(wrong_algorithm)
    assert algorithm_error.value.code in {"SEARCH_ALGORITHM_INVALID", "SEARCH_ALGORITHM_IMPLEMENTATION_MISMATCH"}

    seeded = replace(experiment, randomness_mode=OnlySearchRandomnessMode.SEEDED, seed=7)
    with pytest.raises(OnlySymbolicSearchError) as randomness_error:
        context_resolver.resolve_verified_context(seeded)
    assert randomness_error.value.code == "SEARCH_RANDOMNESS_INVALID"

    model_assisted = replace(
        experiment,
        decision_engine_binding=OnlySearchDecisionEngineBindingV1(
            OnlySearchDecisionMode.MODEL_ASSISTED,
            "provider",
            "model",
            "1",
            "b" * 64,
            "c" * 64,
        ),
    )
    with pytest.raises(OnlySymbolicSearchError) as decision_error:
        context_resolver.resolve_verified_context(model_assisted)
    assert decision_error.value.code == "SEARCH_DECISION_ENGINE_INVALID"


def _result_reader(layout: OnlyUserDataLayout, datasets: OnlyParquetResearchDatasetSnapshotStore):
    calculations = OnlyParquetResearchCalculationResultStore(layout.research_calculation_result_root, datasets)
    statistics = OnlyParquetResearchStatisticsResultStore(layout.research_statistics_result_root, calculations)
    return OnlyJsonResearchResultStore(layout.research_result_root, statistics, calculations)


def _fresh_process_e2e(root: Path, terminal_result_fingerprint: str | None = None) -> dict[str, str]:
    layout = OnlyUserDataLayout(root)
    datasets = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    generation, search_space = space(max_nodes=1)
    symbolic = OnlyJsonSymbolicSearchStore(root)
    catalog_manager = OnlyQuantAssetCatalogManager(generation)
    if terminal_result_fingerprint is None:
        candidate_dataset, partitions = snapshot()
        dataset = datasets.commit(candidate_dataset, partitions)
        symbolic.commit_search_space(search_space)
        evaluation = _evaluation(dataset.snapshot_fingerprint)
        symbolic.commit_evaluation_contract(evaluation)
        symbolic.commit_algorithm_implementation_manifest(only_deterministic_enumeration_implementation())
        experiment = _experiment(
            search_space.search_space_fingerprint,
            generation.generation_fingerprint,
            dataset.snapshot_fingerprint,
            evaluation.evaluation_contract_fingerprint,
        )
        context_resolver = OnlySymbolicSearchContextResolver(
            symbolic_store=symbolic,
            catalogs=catalog_manager,
            datasets=datasets,
            research_calculation_registry=specification_registry(),
        )
        context = context_resolver.resolve_verified_context(experiment)
        research_results = _result_reader(layout, datasets)
        provenance = OnlyJsonSearchProvenanceStore(
            root,
            catalogs=catalog_manager,
            datasets=datasets,
            research_results=research_results,
            search_contexts=context_resolver,
        )
        provenance.commit_experiment(experiment)
        proposal = enumerate_symbolic_factor_proposals(context.verified_search_space, proposal_limit=1).proposals[0]
        symbolic.commit_proposal(proposal)
        verified_proposal = verify_symbolic_proposal_reconstruction(proposal, context)
        plan = OnlySearchIterationPlanV1(
            experiment.experiment_fingerprint,
            0,
            SYMBOLIC_PROPOSAL_KIND,
            SYMBOLIC_PROPOSAL_SCHEMA_VERSION,
            proposal.proposal_fingerprint,
            (),
            (),
            proposal.proposal_fingerprint,
        )
        provenance.commit_iteration_plan(plan)
        registry = generation.calculation_registry()
        for registration in target_registrations():
            registry.register(registration)
        resolved = resolve_symbolic_research_candidate(
            verified_proposal,
            OnlyResearchSpecificationResolver(registry),
        )
        engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("symbolic-fresh-process"), root))
        runtime_id = engine.add_research_workload(resolved.resolution.workload)
        engine.initialize()
        engine.start()
        execution = engine.run_runtime(runtime_id)
        engine.stop()
        assert execution.status is OnlyRuntimeResultStatus.COMPLETED
        assert execution.research_result_fingerprint is not None
        assert resolved.candidate.candidate_fingerprint is not None
        revision = p9_strategy_case(root / "strategy-authoring").revision
        strategy_reader, strategy_publisher = _only_compose_frozen_strategy_authority(root)
        relation = OnlyStrategyFreezeRelation(
            str(revision.strategy_fingerprint),
            resolved.candidate.candidate_fingerprint,
            execution.research_result_fingerprint,
            ("1" * 64,),
            "2" * 64,
            ("3" * 64,),
        )
        strategy_publisher.publish_verified(_only_authorize_frozen_strategy_publication(revision, relation))
        policies = OnlyQualificationPolicyStore(root)
        policy = OnlyQualificationPolicyRevision(
            "symbolic-fresh-process-gate",
            "1",
            OnlyQualificationGate.RESEARCH_TO_BACKTEST,
            (
                OnlyQualificationCriterion(
                    "has-statistics",
                    OnlyQualificationEvidenceKind.RESEARCH_RESULT,
                    "research.statistics_result_count",
                    "GE",
                    Decimal(1),
                ),
            ),
        )
        policies.put(policy)
        decision_reader, decision_publisher = _only_compose_qualification_decision_authority(root)
        research_reference = OnlySearchResearchResultReferenceV1(
            resolved.resolution.workload.result_plan.fingerprint,
            execution.research_result_fingerprint,
        )
        decision = OnlyQualificationEvaluator(
            strategies=strategy_reader,
            policies=policies,
            research_results=research_results,
            backtest_evidence=OnlyBacktestEvidenceStore(root),
            decisions=decision_publisher,
        ).evaluate(
            subject_strategy_fingerprint=str(revision.strategy_fingerprint),
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            evidence=(
                OnlyQualificationEvidenceReference(
                    OnlyQualificationEvidenceKind.RESEARCH_RESULT,
                    research_reference.result_fingerprint,
                    research_reference.locator_fingerprint,
                    relation.relation_fingerprint,
                ),
            ),
        )
        terminal = OnlySearchIterationResultV1(
            plan.iteration_plan_fingerprint,
            resolved.candidate.candidate_fingerprint,
            True,
            research_reference,
            True,
            decision.decision_fingerprint,
            OnlySearchIterationDisposition.QUALIFICATION_DECISION_RECORDED,
            None,
        )
        provenance = OnlyJsonSearchProvenanceStore(
            root,
            catalogs=catalog_manager,
            datasets=datasets,
            research_results=research_results,
            qualification_decisions=decision_reader,
            freeze_relations=strategy_reader,
            search_contexts=context_resolver,
        )
        provenance.commit_iteration_result(terminal)
    else:
        terminal = None
        # Construct readers first, then exact-load only the supplied terminal identity.
        research_results = _result_reader(layout, datasets)

        # Dataset exact-load is performed after the exact Experiment is reached through the Plan.
        class _ExactDatasetReader:
            def load_verified_table(self, fingerprint: str):  # type: ignore[no-untyped-def]
                return datasets.load_verified_table(fingerprint)

        strategy_reader = OnlyFrozenStrategyRevisionStore(root)
        decision_reader, _decision_publisher = _only_compose_qualification_decision_authority(root)
        context_reader = OnlySymbolicSearchContextResolver(
            symbolic_store=symbolic,
            catalogs=catalog_manager,
            datasets=_ExactDatasetReader(),
            research_calculation_registry=specification_registry(),
        )
        provenance = OnlyJsonSearchProvenanceStore(
            root,
            catalogs=catalog_manager,
            datasets=_ExactDatasetReader(),
            research_results=research_results,
            qualification_decisions=decision_reader,
            freeze_relations=strategy_reader,
            search_contexts=context_reader,
        )
        terminal = provenance.load_iteration_result_verified(terminal_result_fingerprint)
        plan = provenance.load_iteration_plan_verified(terminal.iteration_plan_fingerprint)
        experiment = provenance.load_experiment_verified(plan.experiment_fingerprint)
        assert isinstance(experiment, OnlySearchExperimentManifestV2)
        context_resolver = OnlySymbolicSearchContextResolver(
            symbolic_store=symbolic,
            catalogs=catalog_manager,
            datasets=_ExactDatasetReader(),
            research_calculation_registry=specification_registry(),
        )
        context = context_resolver.resolve_verified_context(experiment)
        verified_proposal = context_resolver.load_proposal_occurrence_contextual_verified(experiment, plan)
        proposal = verified_proposal.proposal
        loaded_space = context.verified_search_space.search_space
        registry = generation.calculation_registry()
        for registration in target_registrations():
            registry.register(registration)
        resolved = resolve_symbolic_research_candidate(
            verified_proposal,
            OnlyResearchSpecificationResolver(registry),
        )
        assert loaded_space == search_space
        assert resolved.candidate.candidate_fingerprint == terminal.candidate_fingerprint
    assert terminal is not None
    return {
        "experiment": experiment.experiment_fingerprint,
        "space": search_space.search_space_fingerprint,
        "proposal": proposal.proposal_fingerprint,
        "graph": proposal.graph_fingerprint,
        "candidate": terminal.candidate_fingerprint or "",
        "research": terminal.research_result_reference.result_fingerprint
        if terminal.research_result_reference is not None
        else "",
        "locator": terminal.research_result_reference.locator_fingerprint
        if terminal.research_result_reference is not None
        else "",
        "iteration_result": terminal.iteration_result_fingerprint,
        "qualification": terminal.qualification_decision_fingerprint or "",
        "freeze_relation": relation.relation_fingerprint
        if terminal_result_fingerprint is None
        else next(
            item.subject_binding_fingerprint
            for item in decision_reader.load_verified(terminal.qualification_decision_fingerprint).evidence
            if item.kind is OnlyQualificationEvidenceKind.RESEARCH_RESULT
        )
        or "",
    }


def test_fresh_process_reconstructs_experiment_to_research_result_from_authority_roots(tmp_path) -> None:
    program = (
        "import json,sys; from pathlib import Path; "
        "from tests.research.search.symbolic.test_research_and_provenance_integration import _fresh_process_e2e; "
        "value=None if sys.argv[2]=='NONE' else sys.argv[2]; print(json.dumps(_fresh_process_e2e(Path(sys.argv[1]),value)))"
    )
    first = json.loads(subprocess.check_output([sys.executable, "-c", program, str(tmp_path), "NONE"], text=True))
    second = json.loads(
        subprocess.check_output(
            [sys.executable, "-c", program, str(tmp_path), first["iteration_result"]],
            text=True,
        )
    )
    assert first == second


def test_runtime_upgrade_preserves_terminal_history_but_blocks_reenumeration(tmp_path) -> None:
    chain = _fresh_process_e2e(tmp_path)
    layout = OnlyUserDataLayout(tmp_path)
    datasets = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    generation, _search_space = space(max_nodes=1)
    symbolic = OnlyJsonSymbolicSearchStore(tmp_path)
    catalog_manager = OnlyQuantAssetCatalogManager(generation)
    research_results = _result_reader(layout, datasets)
    strategies = OnlyFrozenStrategyRevisionStore(tmp_path)
    decisions, _publisher = _only_compose_qualification_decision_authority(tmp_path)
    runtime_a_reader = OnlySymbolicSearchContextResolver(
        symbolic_store=symbolic,
        catalogs=catalog_manager,
        datasets=datasets,
        research_calculation_registry=specification_registry(),
    )
    provenance_a = OnlyJsonSearchProvenanceStore(
        tmp_path,
        catalogs=catalog_manager,
        datasets=datasets,
        research_results=research_results,
        qualification_decisions=decisions,
        freeze_relations=strategies,
        search_contexts=runtime_a_reader,
    )
    terminal = provenance_a.load_iteration_result_verified(chain["iteration_result"])
    plan = provenance_a.load_iteration_plan_verified(terminal.iteration_plan_fingerprint)
    experiment = provenance_a.load_experiment_verified(plan.experiment_fingerprint)
    assert isinstance(experiment, OnlySearchExperimentManifestV2)
    historical = symbolic.load_algorithm_implementation_manifest_intrinsic_verified(
        experiment.search_algorithm_binding.implementation_fingerprint
    )
    runtime_b = replace(
        historical,
        resources=(replace(historical.resources[0], byte_sha256="f" * 64), *historical.resources[1:]),
    )
    upgraded_reader = OnlySymbolicSearchContextResolver(
        symbolic_store=symbolic,
        catalogs=catalog_manager,
        datasets=datasets,
        research_calculation_registry=specification_registry(),
        algorithm_implementation=runtime_b,
    )
    provenance_b = OnlyJsonSearchProvenanceStore(
        tmp_path,
        catalogs=catalog_manager,
        datasets=datasets,
        research_results=research_results,
        qualification_decisions=decisions,
        freeze_relations=strategies,
        search_contexts=upgraded_reader,
    )
    assert provenance_b.load_iteration_result_verified(chain["iteration_result"]) == terminal
    assert provenance_b.load_experiment_verified(experiment.experiment_fingerprint) == experiment
    assert (
        symbolic.load_algorithm_implementation_manifest_intrinsic_verified(historical.implementation_fingerprint)
        == historical
    )
    with pytest.raises(OnlySymbolicSearchError, match="SEARCH_ALGORITHM_RUNTIME_MISMATCH"):
        upgraded_reader.load_proposal_occurrence_contextual_verified(experiment, plan)


def test_existing_qualification_and_b31_subject_chain_close_without_copying_outcome(tmp_path) -> None:
    chain = _fresh_process_e2e(tmp_path)
    layout = OnlyUserDataLayout(tmp_path)
    datasets = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    research_results = _result_reader(layout, datasets)
    strategies = OnlyFrozenStrategyRevisionStore(tmp_path)
    decision_reader, _decision_publisher = _only_compose_qualification_decision_authority(tmp_path)
    decision = decision_reader.load_verified(chain["qualification"])
    assert decision.outcome is OnlyQualificationOutcome.APPROVED

    generation, search_space = space(max_nodes=1)
    symbolic = OnlyJsonSymbolicSearchStore(tmp_path)
    catalog_manager = OnlyQuantAssetCatalogManager(generation)
    context_resolver = OnlySymbolicSearchContextResolver(
        symbolic_store=symbolic,
        catalogs=catalog_manager,
        datasets=datasets,
        research_calculation_registry=specification_registry(),
    )
    provenance = OnlyJsonSearchProvenanceStore(
        tmp_path,
        catalogs=catalog_manager,
        datasets=datasets,
        research_results=research_results,
        qualification_decisions=decision_reader,
        freeze_relations=strategies,
        search_contexts=context_resolver,
    )
    loaded = provenance.load_iteration_result_verified(chain["iteration_result"])
    assert loaded.qualification_decision_fingerprint == decision.decision_fingerprint
    assert "APPROVED" not in loaded.to_dict().values()
