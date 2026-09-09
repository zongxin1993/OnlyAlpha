from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry

from onlyalpha.application.search_product import only_search_experiment_work_id
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngineConfig
from onlyalpha.engine.engine import OnlyEngine
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.persistence.postgres import (
    OnlyPostgresResearchExecutionStore,
    OnlyPostgresResearchRunStore,
)
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.quant_assets import OnlyQuantAssetCatalogManager
from onlyalpha.research import (
    OnlyJsonResearchResultStore,
    OnlyJsonResearchSummaryStatisticsResultStore,
    OnlyParquetResearchCalculationResultStore,
    OnlyParquetResearchDatasetSnapshotStore,
    OnlyParquetResearchStatisticsResultStore,
    OnlyResearchEffectSummaryExecutor,
    OnlyResearchResultAssembler,
    OnlyResearchStatisticsResultReader,
)
from onlyalpha.research.command import OnlyResearchCommandService
from onlyalpha.research.evaluation.definition import OnlyResearchStatisticsMethod
from onlyalpha.research.evaluation.summary.metric import only_research_effect_metric
from onlyalpha.research.execution.model import OnlyResearchRunAttemptId, OnlyResearchWorkerInstanceId
from onlyalpha.research.experiment import (
    OnlyJsonSearchProvenanceStore,
    OnlySearchAlgorithmBindingV1,
    OnlySearchBudgetV1,
    OnlySearchDecisionEngineBindingV1,
    OnlySearchDecisionMode,
    OnlySearchEvaluationContextReferenceV1,
    OnlySearchExperimentManifestV3,
    OnlySearchHypothesisV1,
    OnlySearchPolicyReferenceV1,
    OnlySearchRandomnessMode,
    OnlySearchSpaceReferenceV1,
    OnlySearchWorkflowBindingV1,
)
from onlyalpha.research.run import OnlyResearchRunId
from onlyalpha.research.run.admission import OnlyResearchRunAdmissionService
from onlyalpha.research.search.parameter import (
    PARAMETER_SEARCH_POLICY_KIND,
    PARAMETER_SEARCH_SPACE_KIND,
    OnlyJsonParameterSearchStore,
    OnlyParameterFactorSearchSpaceV1,
    OnlyParameterObjectiveDirection,
    OnlyParameterResearchCommandGatewayV1,
    OnlyParameterResearchEvidenceFinalizerV1,
    OnlyParameterResearchEvidenceReader,
    OnlyParameterSearchContextResolver,
    OnlyParameterSearchControllerV1,
    OnlyParameterSearchError,
    OnlyParameterSearchPolicyV1,
    OnlyParameterTieBreakerV1,
    decide_parameter_search_v1,
    materialize_parameter_proposals,
    only_deterministic_coarse_to_fine_implementation,
    parameter_submission_key,
    plans_for_feedback_decision,
    resolve_parameter_research_candidate,
    verify_parameter_feedback_decision_occurrence,
)
from onlyalpha.research.search.symbolic import (
    SYMBOLIC_EVALUATION_CONTRACT_KIND,
    OnlyJsonSymbolicSearchStore,
    OnlySymbolicResearchEvaluationContractV1,
)
from onlyalpha.research.specification.model import (
    OnlyResearchScientificEvidenceSpec,
    OnlyResearchSeriesSelector,
    OnlyResearchSignalEvidenceSpec,
    OnlyResearchSpecification,
)
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver
from onlyalpha.runtime.result import OnlyRuntimeResultStatus
from tests.research.calculation.support import snapshot
from tests.research.search.symbolic.support import catalog
from tests.research.specification.support import registry as research_registry
from tests.research.specification.support import specification
from tests.research.sweep.support import definition
from tests.runtime_generation_support import only_ready_test_generation

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]

_NOW = datetime(2026, 9, 7, 1, 2, 3, tzinfo=UTC)
_PRIMARY = only_research_effect_metric(OnlyResearchStatisticsMethod.IC, "mean").metric_id
_TIE = only_research_effect_metric(OnlyResearchStatisticsMethod.IC, "information_ratio").metric_id


def _stores(root: Path):  # type: ignore[no-untyped-def]
    layout = OnlyUserDataLayout(root)
    datasets = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    calculations = OnlyParquetResearchCalculationResultStore(layout.research_calculation_result_root, datasets)
    statistics = OnlyParquetResearchStatisticsResultStore(layout.research_statistics_result_root, calculations)
    summaries = OnlyJsonResearchSummaryStatisticsResultStore(
        layout.research_statistics_result_root,
        statistics,
        audit_time=lambda: _NOW + timedelta(seconds=4),
    )
    statistics_reader = OnlyResearchStatisticsResultReader(
        layout.research_statistics_result_root,
        statistics,
        summaries,
    )
    research = OnlyJsonResearchResultStore(layout.research_result_root, statistics_reader, calculations)
    return layout, datasets, calculations, statistics, summaries, statistics_reader, research


def _topology(root: Path):  # type: ignore[no-untyped-def]
    layout, datasets, _calculations, _statistics, _summaries, statistics_reader, research = _stores(root)
    generation = catalog()
    catalogs = OnlyQuantAssetCatalogManager(generation)
    parameters = OnlyJsonParameterSearchStore(root)
    evaluations = OnlyJsonSymbolicSearchStore(root)
    contexts = OnlyParameterSearchContextResolver(
        parameter_store=parameters,
        evaluations=evaluations,
        catalogs=catalogs,
        datasets=datasets,
        research_calculation_registry=research_registry(),
    )
    provenance = OnlyJsonSearchProvenanceStore(
        root,
        catalogs=catalogs,
        datasets=datasets,
        research_results=research,
        search_contexts=contexts,
    )
    return layout, datasets, statistics_reader, research, parameters, evaluations, contexts, provenance


def _initialize(root: Path, *, partial_plan_batch: bool) -> None:
    _layout, datasets, statistics, research, parameters, evaluations, contexts, provenance = _topology(root)
    candidate, partitions = snapshot()
    dataset = datasets.commit(candidate, partitions)
    generation = catalog()
    space = OnlyParameterFactorSearchSpaceV1.from_sweep(
        catalog_generation_fingerprint=generation.generation_fingerprint,
        sweep_definition=definition(dataset.snapshot_fingerprint, candidates=(3, 4)),
        candidate_template_node_id="momentum",
        candidate_output_name="factor_value",
        calculation_registry=research_registry(),
    )
    policy = OnlyParameterSearchPolicyV1(
        primary_metric_selector=_PRIMARY,
        objective_direction=OnlyParameterObjectiveDirection.MAXIMIZE,
        required_constraints=(),
        ordered_tie_breakers=(OnlyParameterTieBreakerV1(_TIE, OnlyParameterObjectiveDirection.MAXIMIZE),),
        minimum_improvement=Decimal("0.010000000000"),
        max_no_improvement_decisions=2,
        batch_size=2,
        coarse_stride=1,
    )
    base_specification = specification(dataset.snapshot_fingerprint)
    scientific_specification = OnlyResearchSpecification(
        base_specification.dataset_snapshot_fingerprint,
        base_specification.calculations,
        base_specification.statistics,
        OnlyResearchScientificEvidenceSpec(
            "feature",
            (OnlyResearchSeriesSelector("feature", "momentum", "factor_value"),),
            OnlyResearchSignalEvidenceSpec(),
        ),
        2,
    )
    evaluation = OnlySymbolicResearchEvaluationContractV1.from_specification(scientific_specification, "feature")
    algorithm = only_deterministic_coarse_to_fine_implementation()
    parameters.commit_search_space(space)
    parameters.commit_policy(policy)
    parameters.commit_algorithm_manifest(algorithm)
    evaluations.commit_evaluation_contract(evaluation)
    experiment = OnlySearchExperimentManifestV3(
        OnlySearchHypothesisV1("B3.3 real-authority deterministic recovery"),
        OnlySearchAlgorithmBindingV1(
            algorithm.algorithm_id,
            algorithm.algorithm_semantic_version,
            algorithm.implementation_fingerprint,
            algorithm.source_revision,
        ),
        OnlySearchSpaceReferenceV1(PARAMETER_SEARCH_SPACE_KIND, 1, space.search_space_fingerprint),
        OnlySearchEvaluationContextReferenceV1(
            SYMBOLIC_EVALUATION_CONTRACT_KIND, 1, evaluation.evaluation_contract_fingerprint
        ),
        OnlySearchPolicyReferenceV1(PARAMETER_SEARCH_POLICY_KIND, 1, policy.policy_fingerprint),
        OnlySearchRandomnessMode.NONE,
        None,
        OnlySearchBudgetV1(2, 2, 1),
        generation.generation_fingerprint,
        dataset.snapshot_fingerprint,
        OnlySearchWorkflowBindingV1("parameter.factor.search", "1"),
        OnlySearchDecisionEngineBindingV1(OnlySearchDecisionMode.DETERMINISTIC),
    )
    for proposal in materialize_parameter_proposals(space, research_registry()):
        parameters.commit_proposal(proposal)
    provenance.commit_experiment(experiment)
    runtime_generations = _runtime_generations(root)
    generation_fingerprint = runtime_generations.projection().active_for_new_work
    assert generation_fingerprint is not None
    runtime_generations.bind_work_exact(
        only_search_experiment_work_id(experiment.experiment_fingerprint),
        generation_fingerprint,
        actor="parameter-search-test-admission",
        occurred_at=_NOW + timedelta(seconds=1),
    )
    context = contexts.resolve_verified_context(experiment)
    if not partial_plan_batch:
        _controller(root).advance(context)
        return
    decision = decide_parameter_search_v1(
        experiment_fingerprint=experiment.experiment_fingerprint,
        proposals=context.proposals,
        policy=policy,
        algorithm_implementation_fingerprint=algorithm.implementation_fingerprint,
        budget=experiment.search_budget,
        evidence=(),
    )
    verified = verify_parameter_feedback_decision_occurrence(
        context=context,
        provenance=provenance,
        evidence_reader=OnlyParameterResearchEvidenceReader(
            iteration_results=provenance,
            iteration_plans=provenance,
            research_results=research,
            statistics_results=statistics,
        ),
        decisions=parameters,
        candidate_decision=decision,
    )
    parameters.commit_feedback_decision(verified)
    provenance.commit_iteration_plan(plans_for_feedback_decision(decision, context.proposals)[0])


def _context_and_authorities(root: Path):  # type: ignore[no-untyped-def]
    _layout, _datasets, statistics, research, parameters, _evaluations, contexts, provenance = _topology(root)
    experiments = tuple((root / "research/search-provenance/experiments/sha256").glob("*/*/manifest.json"))
    assert len(experiments) == 1
    payload = json.loads(experiments[0].read_text(encoding="utf-8"))
    experiment = OnlySearchExperimentManifestV3.from_dict(payload)
    context = contexts.resolve_verified_context(experiment)
    evidence = OnlyParameterResearchEvidenceReader(
        iteration_results=provenance,
        iteration_plans=provenance,
        research_results=research,
        statistics_results=statistics,
    )
    return context, parameters, provenance, evidence


def _controller(root: Path) -> OnlyParameterSearchControllerV1:
    context, parameters, provenance, evidence = _context_and_authorities(root)
    del context
    return OnlyParameterSearchControllerV1(
        parameter_store=parameters,
        provenance=provenance,
        evidence_reader=evidence,
    )


def _runtime_generations(root: Path) -> OnlyRuntimeGenerationRegistry:
    authority = OnlyRuntimeGenerationRegistry(root / "runtime-generation-authority")
    if not (authority.root / "generation-events.jsonl").exists():
        generation = only_ready_test_generation(authority, "a", _NOW)
        authority.activate_for_new_work(
            expected_current=None,
            target=generation,
            actor="test-operator",
            occurred_at=_NOW + timedelta(seconds=1),
        )
    return authority


def _commands(root: Path, dsn: str) -> OnlyParameterResearchCommandGatewayV1:
    layout, datasets, calculations, statistics_store, summaries, statistics_reader, research = _stores(root)
    del layout
    store = OnlyPostgresResearchRunStore(dsn)
    admission = OnlyResearchRunAdmissionService(
        resolver=OnlyResearchSpecificationResolver(research_registry()),
        dataset_store=datasets,
        run_store=store,
        now_utc=lambda: _NOW + timedelta(seconds=2),
    )
    commands = OnlyResearchCommandService(
        admission=admission,
        store=store,
        now_utc=lambda: _NOW + timedelta(seconds=2),
        runtime_generations=_runtime_generations(root),
    )
    finalizer = OnlyParameterResearchEvidenceFinalizerV1(
        research_results=research,
        summary_executor=OnlyResearchEffectSummaryExecutor(statistics_store, summaries),
        result_assembler=OnlyResearchResultAssembler(
            statistics_reader,
            calculation_result_store=calculations,
            audit_time=lambda: _NOW + timedelta(seconds=5),
        ),
    )
    return OnlyParameterResearchCommandGatewayV1(commands, finalizer)


def _recover_plan_batch(root: Path) -> None:
    context, _parameters, provenance, _evidence = _context_and_authorities(root)
    with pytest.raises(OnlyParameterSearchError, match="SEARCH_ROUND_BARRIER_OPEN"):
        _controller(root).advance(context)
    assert len(provenance.iteration_plans_for_experiment_verified(context.experiment.experiment_fingerprint)) == 2


def _reconcile(root: Path, dsn: str) -> tuple[object | None, ...]:
    context, _parameters, _provenance, _evidence = _context_and_authorities(root)
    return _controller(root).reconcile_open_plans(
        context,
        resolver=OnlyResearchSpecificationResolver(research_registry()),
        commands=_commands(root, dsn),
    )


def _execute_research(root: Path, dsn: str) -> None:
    context, _parameters, provenance, _evidence = _context_and_authorities(root)
    command_store = OnlyPostgresResearchRunStore(dsn)
    execution_store = OnlyPostgresResearchExecutionStore(dsn)
    resolver = OnlyResearchSpecificationResolver(research_registry())
    proposals = {item.proposal_fingerprint: item for item in context.proposals}
    for index, plan in enumerate(
        provenance.iteration_plans_for_experiment_verified(context.experiment.experiment_fingerprint)
    ):
        proposal = proposals[plan.proposal_fingerprint]
        resolved = resolve_parameter_research_candidate(context, proposal, resolver)
        receipt = command_store.find_product_command_receipt(parameter_submission_key(plan))
        assert receipt is not None
        run_id = OnlyResearchRunId(receipt.outcome_ref.outcome_id)
        claim = execution_store.claim_next(
            worker_instance_id=OnlyResearchWorkerInstanceId(f"00000000-0000-4000-8000-{index + 101:012d}"),
            attempt_id=OnlyResearchRunAttemptId(f"00000000-0000-4000-8000-{index + 201:012d}"),
            lease_duration=timedelta(minutes=2),
            max_attempts=1,
            run_started_at=_NOW + timedelta(seconds=3),
            eligible_run_ids=(run_id.value,),
        )
        assert claim is not None
        engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("parameter-recovery"), root))
        runtime_id = engine.add_research_workload(resolved.resolution.workload)
        engine.initialize()
        engine.start()
        outcome = engine.run_runtime(runtime_id)
        engine.stop()
        assert outcome.status is OnlyRuntimeResultStatus.COMPLETED
        execution_store.complete(
            claim=claim,
            run_finished_at=_NOW + timedelta(seconds=4),
            research_result_fingerprint=outcome.research_result_fingerprint,
            artifact_content_fingerprint=outcome.artifact_content_fingerprint,
            calculation_execution_evidence_fingerprints=outcome.calculation_execution_evidence_fingerprints,
        )


def _snapshot(root: Path, dsn: str) -> dict[str, object]:
    context, parameters, provenance, _evidence = _context_and_authorities(root)
    plans = provenance.iteration_plans_for_experiment_verified(context.experiment.experiment_fingerprint)
    results = tuple(provenance.terminal_result_for_plan_verified(item.iteration_plan_fingerprint) for item in plans)
    assert all(item is not None for item in results)
    frontier = parameters.load_frontier_fingerprint(context.experiment.experiment_fingerprint)
    assert frontier is not None
    decision = parameters.load_feedback_decision_intrinsic_verified(frontier)
    decision_fingerprints = list(dict.fromkeys(item.decision_output_fingerprint for item in plans))
    if not decision_fingerprints or decision_fingerprints[-1] != frontier:
        decision_fingerprints.append(frontier)
    decisions = tuple(parameters.load_feedback_decision_intrinsic_verified(item) for item in decision_fingerprints)
    with psycopg.connect(dsn) as connection:
        receipt_count = connection.execute("SELECT count(*) FROM product_command_receipt").fetchone()[0]
        run_count = connection.execute("SELECT count(*) FROM research_run").fetchone()[0]
        execution_attempt_count = connection.execute("SELECT count(*) FROM research_run_attempt").fetchone()[0]
    research_ids = tuple(item.research_result_reference.result_fingerprint for item in results if item is not None)
    statistic_ids = []
    _layout, _datasets, _calculations, _statistics, _summaries, _statistics_reader, research = _stores(root)
    for item in results:
        assert item is not None and item.research_result_reference is not None
        loaded = research.load_verified(item.research_result_reference.locator_fingerprint)
        statistic_ids.extend(value.statistics_result_fingerprint for value in loaded.manifest.statistics_results)
    return {
        "experiment": context.experiment.experiment_fingerprint,
        "policy": context.policy.policy_fingerprint,
        "space": context.search_space.search_space_fingerprint,
        "algorithm": context.historical_algorithm_manifest.implementation_fingerprint,
        "decisions": tuple(decision_fingerprints),
        "decision_payloads": tuple(item.to_dict() for item in decisions),
        "plans": tuple(item.iteration_plan_fingerprint for item in plans),
        "proposals": tuple(item.proposal_fingerprint for item in context.proposals),
        "candidates": tuple(item.candidate_fingerprint for item in results if item is not None),
        "research": research_ids,
        "statistics": tuple(statistic_ids),
        "frontier": decision.feedback_decision_fingerprint,
        "final_decision_kind": decision.decision_kind.value,
        "final_stop_reason": None if decision.stop_reason is None else decision.stop_reason.value,
        "proposal_budget_consumed": len(plans),
        "budget": provenance.search_restart_state_verified(context.experiment.experiment_fingerprint),
        "receipt_count": receipt_count,
        "run_count": run_count,
        "execution_attempt_count": execution_attempt_count,
    }


def _recovery_state(root: Path, dsn: str) -> dict[str, int]:
    context, _parameters, provenance, _evidence = _context_and_authorities(root)
    plans = provenance.iteration_plans_for_experiment_verified(context.experiment.experiment_fingerprint)
    terminal = tuple(
        item
        for plan in plans
        if (item := provenance.terminal_result_for_plan_verified(plan.iteration_plan_fingerprint)) is not None
    )
    with psycopg.connect(dsn) as connection:
        receipts = connection.execute("SELECT count(*) FROM product_command_receipt").fetchone()[0]
        runs = connection.execute("SELECT count(*) FROM research_run").fetchone()[0]
    return {
        "plans": len(plans),
        "terminal_results": len(terminal),
        "research_budget_consumed": sum(int(item.research_attempted) for item in terminal),
        "qualification_budget_consumed": sum(int(item.qualification_attempted) for item in terminal),
        "receipts": receipts,
        "runs": runs,
    }


def _run_stage(root: Path, dsn: str, stage: str) -> dict[str, object] | None:
    if stage == "initialize-partial":
        _initialize(root, partial_plan_batch=True)
    elif stage == "recover-plans":
        _recover_plan_batch(root)
    elif stage in {"submit", "replay", "project"}:
        outcomes = _reconcile(root, dsn)
        if stage != "project":
            assert outcomes == (None, None)
        else:
            assert all(item is not None for item in outcomes)
            return _snapshot(root, dsn)
    elif stage == "advance":
        context, _parameters, _provenance, _evidence = _context_and_authorities(root)
        _controller(root).advance(context)
        return _snapshot(root, dsn)
    elif stage == "execute":
        _execute_research(root, dsn)
    else:  # pragma: no cover - internal test command guard
        raise ValueError(stage)
    return _recovery_state(root, dsn)


def _fresh_stage(root: Path, dsn: str, stage: str) -> dict[str, object] | None:
    program = (
        "import json,sys; from pathlib import Path; "
        "from tests.research.postgres.test_parameter_search_recovery import _run_stage; "
        "value=_run_stage(Path(sys.argv[1]),sys.argv[2],sys.argv[3]); "
        "print(json.dumps(value))"
    )
    environment = dict(os.environ)
    environment["ONLYALPHA_TEST_POSTGRES_DSN"] = dsn
    value = subprocess.check_output(
        [sys.executable, "-c", program, str(root), dsn, stage],
        text=True,
        env=environment,
    )
    return json.loads(value)


def _reset_database(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    OnlyPostgresMigrationAuthority(dsn).migrate()


def _continuous(root: Path, dsn: str) -> dict[str, object]:
    _initialize(root, partial_plan_batch=False)
    assert _reconcile(root, dsn) == (None, None)
    _execute_research(root, dsn)
    assert all(item is not None for item in _reconcile(root, dsn))
    context, _parameters, _provenance, _evidence = _context_and_authorities(root)
    _controller(root).advance(context)
    return _snapshot(root, dsn)


def test_at_18_24_real_authority_fresh_process_recovery_is_exact(postgres_dsn: str, tmp_path: Path) -> None:
    _reset_database(postgres_dsn)
    continuous = json.loads(json.dumps(_continuous(tmp_path / "continuous", postgres_dsn)))

    _reset_database(postgres_dsn)
    recovered_root = tmp_path / "recovered"
    states = {
        stage: _fresh_stage(recovered_root, postgres_dsn, stage)
        for stage in ("initialize-partial", "recover-plans", "submit", "replay", "execute")
    }
    projected = _fresh_stage(recovered_root, postgres_dsn, "project")
    assert projected is not None and len(projected["decisions"]) == 1
    assert _fresh_stage(recovered_root, postgres_dsn, "project") == projected
    recovered = _fresh_stage(recovered_root, postgres_dsn, "advance")

    assert recovered == continuous
    assert states == {
        "initialize-partial": {
            "plans": 1,
            "terminal_results": 0,
            "research_budget_consumed": 0,
            "qualification_budget_consumed": 0,
            "receipts": 0,
            "runs": 0,
        },
        "recover-plans": {
            "plans": 2,
            "terminal_results": 0,
            "research_budget_consumed": 0,
            "qualification_budget_consumed": 0,
            "receipts": 0,
            "runs": 0,
        },
        "submit": {
            "plans": 2,
            "terminal_results": 0,
            "research_budget_consumed": 0,
            "qualification_budget_consumed": 0,
            "receipts": 2,
            "runs": 2,
        },
        "replay": {
            "plans": 2,
            "terminal_results": 0,
            "research_budget_consumed": 0,
            "qualification_budget_consumed": 0,
            "receipts": 2,
            "runs": 2,
        },
        "execute": {
            "plans": 2,
            "terminal_results": 0,
            "research_budget_consumed": 0,
            "qualification_budget_consumed": 0,
            "receipts": 2,
            "runs": 2,
        },
    }
    assert continuous["receipt_count"] == continuous["run_count"] == 2
    assert continuous["execution_attempt_count"] == 2
    assert len(continuous["decisions"]) == 2
    assert len(continuous["decision_payloads"]) == 2
    assert len(continuous["research"]) == 2
    assert len(continuous["statistics"]) == 4
    assert continuous["final_decision_kind"] == "STOP"
    assert continuous["final_stop_reason"] == "NO_ELIGIBLE_EVIDENCE"
    assert continuous["budget"] == [2, 2, 0]
