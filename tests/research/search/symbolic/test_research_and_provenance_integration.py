from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

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
    OnlySearchExperimentManifestV1,
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
    SYMBOLIC_PROPOSAL_KIND,
    SYMBOLIC_PROPOSAL_SCHEMA_VERSION,
    SYMBOLIC_SEARCH_SPACE_KIND,
    SYMBOLIC_SEARCH_SPACE_SCHEMA_VERSION,
    OnlyJsonSymbolicSearchStore,
    OnlySymbolicResearchEvaluationTemplateV1,
    OnlySymbolicSearchError,
    enumerate_symbolic_factor_proposals,
    resolve_symbolic_research_candidate,
    run_symbolic_search_workflow,
    verify_symbolic_search_space,
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
from tests.research.calculation.support import snapshot
from tests.research.specification.support import specification

from .support import space


@dataclass(frozen=True)
class _Snapshot:
    snapshot_fingerprint: str


@dataclass(frozen=True)
class _Dataset:
    snapshot: _Snapshot


class _Datasets:
    def __init__(self, fingerprint: str) -> None:
        self.value = _Dataset(_Snapshot(fingerprint))

    def load_verified_table(self, fingerprint: str) -> _Dataset:
        if fingerprint != self.value.snapshot.snapshot_fingerprint:
            raise KeyError(fingerprint)
        return self.value


def _experiment(search_space_fingerprint: str, catalog_fingerprint: str, dataset_fingerprint: str):
    return OnlySearchExperimentManifestV1(
        OnlySearchHypothesisV1("A fixed admitted momentum bridge can compose exact reusable calculations."),
        OnlySearchAlgorithmBindingV1(
            DETERMINISTIC_ENUMERATION_ALGORITHM_ID,
            DETERMINISTIC_ENUMERATION_ALGORITHM_SEMANTIC_VERSION,
            "1" * 64,
            "b3.2",
        ),
        OnlySearchSpaceReferenceV1(
            SYMBOLIC_SEARCH_SPACE_KIND,
            SYMBOLIC_SEARCH_SPACE_SCHEMA_VERSION,
            search_space_fingerprint,
        ),
        OnlySearchRandomnessMode.NONE,
        None,
        OnlySearchBudgetV1(3, 2, 1),
        catalog_fingerprint,
        dataset_fingerprint,
        OnlySearchWorkflowBindingV1("symbolic.factor.search", "1"),
        OnlySearchDecisionEngineBindingV1(OnlySearchDecisionMode.DETERMINISTIC),
    )


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
    symbolic = OnlyJsonSymbolicSearchStore(tmp_path)
    symbolic.commit_search_space(search_space)
    dataset = "a" * 64
    experiment = _experiment(search_space.search_space_fingerprint, generation.generation_fingerprint, dataset)
    provenance = OnlyJsonSearchProvenanceStore(
        tmp_path,
        catalogs=OnlyQuantAssetCatalogManager(generation),
        datasets=_Datasets(dataset),
        search_spaces=symbolic,
        proposals=symbolic,
    )
    provenance.commit_experiment(experiment)
    proposal = enumerate_symbolic_factor_proposals(
        verify_symbolic_search_space(search_space, generation), proposal_limit=1
    ).proposals[0]
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
    experiment = _experiment(search_space.search_space_fingerprint, generation.generation_fingerprint, dataset)
    provenance = OnlyJsonSearchProvenanceStore(
        tmp_path,
        catalogs=OnlyQuantAssetCatalogManager(generation),
        datasets=_Datasets(dataset),
    )
    with pytest.raises(OnlySearchProvenanceError) as error:
        provenance.commit_experiment(experiment)
    assert error.value.code == "SEARCH_EXTERNAL_REFERENCE_READER_UNAVAILABLE"


def test_proposal_uses_normal_resolver_candidate_identity_and_fixed_template() -> None:
    generation, search_space = space(max_nodes=1)
    proposal = enumerate_symbolic_factor_proposals(
        verify_symbolic_search_space(search_space, generation), proposal_limit=1
    ).proposals[0]
    registry = generation.calculation_registry()
    assert isinstance(registry, OnlyCalculationRegistry)
    for registration in target_registrations():
        registry.register(registration)
    template = OnlySymbolicResearchEvaluationTemplateV1(_scientific_template("a" * 64), "feature")
    resolved = resolve_symbolic_research_candidate(
        proposal,
        template,
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
    proposal = enumerate_symbolic_factor_proposals(
        verify_symbolic_search_space(search_space, generation), proposal_limit=1
    ).proposals[0]
    registry = generation.calculation_registry()
    for registration in target_registrations():
        registry.register(registration)
    resolved = resolve_symbolic_research_candidate(
        proposal,
        OnlySymbolicResearchEvaluationTemplateV1(
            _scientific_template(dataset.snapshot_fingerprint),
            "feature",
        ),
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
    verified = verify_symbolic_search_space(search_space, generation)
    experiment = _experiment(search_space.search_space_fingerprint, generation.generation_fingerprint, "a" * 64)
    registry = generation.calculation_registry()
    for registration in target_registrations():
        registry.register(registration)
    resolver = OnlyResearchSpecificationResolver(registry)
    template = OnlySymbolicResearchEvaluationTemplateV1(_scientific_template("a" * 64), "feature")

    sequences = []
    for name, decision in (("pass", "e" * 64), ("fail", "f" * 64)):
        provenance = _CollectingProvenance()
        research = _FakeResearch()
        qualification = _FakeQualification(decision)
        outcome = run_symbolic_search_workflow(
            experiment=experiment,
            verified_space=verified,
            symbolic_store=OnlyJsonSymbolicSearchStore(tmp_path / name),
            provenance=provenance,
            evaluation_template=template,
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
    verified = verify_symbolic_search_space(search_space, generation)
    experiment = _experiment(search_space.search_space_fingerprint, generation.generation_fingerprint, "a" * 64)
    registry = generation.calculation_registry()
    for registration in target_registrations():
        registry.register(registration)
    common = {
        "verified_space": verified,
        "symbolic_store": OnlyJsonSymbolicSearchStore(tmp_path),
        "provenance": _CollectingProvenance(),
        "evaluation_template": OnlySymbolicResearchEvaluationTemplateV1(_scientific_template("a" * 64), "feature"),
        "resolver": OnlyResearchSpecificationResolver(registry),
    }

    wrong_algorithm = replace(
        experiment,
        search_algorithm_binding=replace(experiment.search_algorithm_binding, algorithm_semantic_version="2"),
    )
    with pytest.raises(OnlySymbolicSearchError) as algorithm_error:
        run_symbolic_search_workflow(experiment=wrong_algorithm, **common)
    assert algorithm_error.value.code == "SEARCH_ALGORITHM_INVALID"

    seeded = replace(experiment, randomness_mode=OnlySearchRandomnessMode.SEEDED, seed=7)
    with pytest.raises(OnlySymbolicSearchError) as randomness_error:
        run_symbolic_search_workflow(experiment=seeded, **common)
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
        run_symbolic_search_workflow(experiment=model_assisted, **common)
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
        experiment = _experiment(
            search_space.search_space_fingerprint,
            generation.generation_fingerprint,
            dataset.snapshot_fingerprint,
        )
        research_results = _result_reader(layout, datasets)
        provenance = OnlyJsonSearchProvenanceStore(
            root,
            catalogs=catalog_manager,
            datasets=datasets,
            research_results=research_results,
            search_spaces=symbolic,
            proposals=symbolic,
        )
        provenance.commit_experiment(experiment)
        proposal = enumerate_symbolic_factor_proposals(
            verify_symbolic_search_space(search_space, generation), proposal_limit=1
        ).proposals[0]
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
        registry = generation.calculation_registry()
        for registration in target_registrations():
            registry.register(registration)
        resolved = resolve_symbolic_research_candidate(
            proposal,
            OnlySymbolicResearchEvaluationTemplateV1(
                _scientific_template(dataset.snapshot_fingerprint),
                "feature",
            ),
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
        terminal = OnlySearchIterationResultV1(
            plan.iteration_plan_fingerprint,
            resolved.candidate.candidate_fingerprint,
            True,
            OnlySearchResearchResultReferenceV1(
                resolved.resolution.workload.result_plan.fingerprint,
                execution.research_result_fingerprint,
            ),
            False,
            None,
            OnlySearchIterationDisposition.RESEARCH_EVIDENCE_RECORDED,
            None,
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

        provenance = OnlyJsonSearchProvenanceStore(
            root,
            catalogs=catalog_manager,
            datasets=_ExactDatasetReader(),
            research_results=research_results,
            search_spaces=symbolic,
            proposals=symbolic,
        )
        terminal = provenance.load_iteration_result_verified(terminal_result_fingerprint)
        plan = provenance.load_iteration_plan_verified(terminal.iteration_plan_fingerprint)
        experiment = provenance.load_experiment_verified(plan.experiment_fingerprint)
        proposal = symbolic.load_proposal_verified(plan.proposal_fingerprint)
        loaded_space = symbolic.load_search_space_verified(experiment.search_space_reference.search_space_fingerprint)
        registry = generation.calculation_registry()
        for registration in target_registrations():
            registry.register(registration)
        resolved = resolve_symbolic_research_candidate(
            proposal,
            OnlySymbolicResearchEvaluationTemplateV1(
                _scientific_template(experiment.dataset_snapshot_fingerprint),
                "feature",
            ),
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


@dataclass(slots=True)
class _QualificationStrategies:
    strategy_fingerprint: str
    relation: OnlyStrategyFreezeRelation

    def load_verified(self, fingerprint: str):  # type: ignore[no-untyped-def]
        if fingerprint != self.strategy_fingerprint:
            raise KeyError(fingerprint)
        return SimpleNamespace(strategy_fingerprint=fingerprint)

    def load_freeze_relation(self, fingerprint: str) -> OnlyStrategyFreezeRelation:
        if fingerprint != self.relation.relation_fingerprint:
            raise KeyError(fingerprint)
        return self.relation


def test_existing_qualification_and_b31_subject_chain_close_without_copying_outcome(tmp_path) -> None:
    chain = _fresh_process_e2e(tmp_path)
    layout = OnlyUserDataLayout(tmp_path)
    datasets = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    research_results = _result_reader(layout, datasets)
    strategy_fingerprint = "8" * 64
    relation = OnlyStrategyFreezeRelation(
        strategy_fingerprint,
        chain["candidate"],
        chain["research"],
        ("1" * 64,),
        "2" * 64,
        ("3" * 64,),
    )
    strategies = _QualificationStrategies(strategy_fingerprint, relation)
    policies = OnlyQualificationPolicyStore(tmp_path / "semantic")
    policy = OnlyQualificationPolicyRevision(
        "symbolic-research-gate",
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
    decision_reader, decision_publisher = _only_compose_qualification_decision_authority(tmp_path / "semantic")
    evidence = (
        OnlyQualificationEvidenceReference(
            OnlyQualificationEvidenceKind.RESEARCH_RESULT,
            chain["research"],
            chain["locator"],
            relation.relation_fingerprint,
        ),
    )
    decision = OnlyQualificationEvaluator(
        strategies=strategies,  # type: ignore[arg-type]
        policies=policies,
        research_results=research_results,
        backtest_evidence=OnlyBacktestEvidenceStore(tmp_path),
        decisions=decision_publisher,
    ).evaluate(
        subject_strategy_fingerprint=strategy_fingerprint,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        evidence=evidence,
    )
    assert decision.outcome is OnlyQualificationOutcome.APPROVED

    generation, search_space = space(max_nodes=1)
    symbolic = OnlyJsonSymbolicSearchStore(tmp_path)
    catalog_manager = OnlyQuantAssetCatalogManager(generation)
    provenance = OnlyJsonSearchProvenanceStore(
        tmp_path,
        catalogs=catalog_manager,
        datasets=datasets,
        research_results=research_results,
        qualification_decisions=decision_reader,
        freeze_relations=strategies,
        search_spaces=symbolic,
        proposals=symbolic,
    )
    first_result = provenance.load_iteration_result_verified(chain["iteration_result"])
    first_plan = provenance.load_iteration_plan_verified(first_result.iteration_plan_fingerprint)
    qualification_plan = OnlySearchIterationPlanV1(
        first_plan.experiment_fingerprint,
        1,
        first_plan.proposal_kind,
        first_plan.proposal_schema_version,
        first_plan.proposal_fingerprint,
        (),
        (),
        first_plan.decision_output_fingerprint,
    )
    provenance.commit_iteration_plan(qualification_plan)
    qualification_result = OnlySearchIterationResultV1(
        qualification_plan.iteration_plan_fingerprint,
        chain["candidate"],
        True,
        OnlySearchResearchResultReferenceV1(chain["locator"], chain["research"]),
        True,
        decision.decision_fingerprint,
        OnlySearchIterationDisposition.QUALIFICATION_DECISION_RECORDED,
        None,
    )
    provenance.commit_iteration_result(qualification_result)
    loaded = provenance.load_iteration_result_verified(qualification_result.iteration_result_fingerprint)
    assert loaded.qualification_decision_fingerprint == decision.decision_fingerprint
    assert "APPROVED" not in loaded.to_dict().values()
