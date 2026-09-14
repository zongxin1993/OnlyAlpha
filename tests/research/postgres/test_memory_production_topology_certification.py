from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from importlib import metadata
from pathlib import Path

import psycopg
import pytest
from onlyalpha_authoring_execution_worker import (
    OnlyAuthoringExecutionGeneration,
    OnlyAuthoringExecutionGenerationStore,
)
from onlyalpha_example_alpha.provider import quant_asset_provider as alpha_provider
from onlyalpha_http_server.main import _GenerationOwnedCatalogReader, _SearchContextReader
from onlyalpha_plugin_indicators.provider import quant_asset_provider as indicator_provider
from onlyalpha_plugin_operators.provider import quant_asset_provider as operator_provider
from onlyalpha_plugin_targets.registration import registrations as target_registrations
from onlyalpha_runtime_generation_manager import (
    OnlyLocalImmutableArtifactStore,
    OnlyRuntimeGenerationBuilder,
    OnlyRuntimeGenerationRegistry,
)
from onlyalpha_runtime_generation_manager.catalog_context import (
    OnlyRuntimeGenerationExactCatalogDescriptorReader,
)

from onlyalpha.backtest.evidence import OnlyBacktestEvidenceManifest, OnlyBacktestEvidenceStore
from onlyalpha.calculation.artifact import only_calculation_distribution_artifact_manifest
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.persistence.postgres.product_command_authority import OnlyPostgresProductCommandAuthority
from onlyalpha.persistence.postgres.research_execution_store import OnlyPostgresResearchExecutionStore
from onlyalpha.persistence.postgres.research_run_store import OnlyPostgresResearchRunStore
from onlyalpha.persistence.postgres.research_source_cut_store import OnlyPostgresResearchSourceCutAuthority
from onlyalpha.quant_assets import (
    OnlyQuantAssetCatalogGeneration,
    OnlyQuantAssetCatalogManager,
    only_quant_asset_distribution_artifact_manifest,
)
from onlyalpha.research.agent import OnlyAgentExactAuthorityReferenceV2, OnlyAgentReferenceLocatorKind
from onlyalpha.research.agent.decision import OnlyAgentExperimentLaunchRecordV1
from onlyalpha.research.agent.occurrence_store import (
    OnlyJsonAgentModelOccurrenceStore,
    OnlyJsonAgentToolOccurrenceStore,
)
from onlyalpha.research.agent.source_cut import OnlyAgentProvenanceClosedCutAuthority
from onlyalpha.research.agent.store import (
    OnlyJsonAgentOrchestrationResourceStore,
    OnlyJsonAgentResearchBriefStore,
    OnlyJsonAgentSessionManifestStore,
)
from onlyalpha.research.calculation.result_store import OnlyParquetResearchCalculationResultStore
from onlyalpha.research.dataset.parquet_store import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.evaluation.definition import OnlyResearchStatisticsMethod
from onlyalpha.research.evaluation.execution import OnlyResearchStatisticsExecutor
from onlyalpha.research.evaluation.factor_pair.result_store import (
    OnlyParquetResearchFactorPairStatisticsResultStore,
)
from onlyalpha.research.evaluation.result_store import OnlyParquetResearchStatisticsResultStore
from onlyalpha.research.evaluation.summary.execution import OnlyResearchFactorPairEffectSummaryExecutor
from onlyalpha.research.evaluation.summary.result_store import OnlyJsonResearchSummaryStatisticsResultStore
from onlyalpha.research.experiment import (
    OnlyJsonSearchProvenanceStore,
    OnlySearchAlgorithmBindingV1,
    OnlySearchBudgetV1,
    OnlySearchDecisionEngineBindingV1,
    OnlySearchDecisionMode,
    OnlySearchEvaluationContextReferenceV1,
    OnlySearchExperimentManifestV3,
    OnlySearchHypothesisV1,
    OnlySearchIterationPlanV1,
    OnlySearchIterationResultV1,
    OnlySearchPolicyReferenceV1,
    OnlySearchRandomnessMode,
    OnlySearchResearchResultReferenceV1,
    OnlySearchSpaceReferenceV1,
    OnlySearchWorkflowBindingV1,
)
from onlyalpha.research.memory.production import (
    OnlyExperimentMemoryProductionBuilder,
    OnlyExperimentMemoryReferenceReadersV1,
)
from onlyalpha.research.memory.source_manifest import (
    OnlyExperimentMemorySourceCutManifestV1,
    OnlyMemoryProjectionError,
)
from onlyalpha.research.memory.store import OnlyExperimentMemoryRevisionStore
from onlyalpha.research.result.assembler import OnlyResearchResultAssembler
from onlyalpha.research.result.result_store import OnlyJsonResearchResultStore
from onlyalpha.research.run import OnlyResearchRun, OnlyResearchRunId, OnlyResearchRunState
from onlyalpha.research.search.parameter import (
    PARAMETER_SEARCH_POLICY_KIND,
    PARAMETER_SEARCH_SPACE_KIND,
    OnlyJsonParameterSearchStore,
    OnlyParameterFactorSearchSpaceV1,
    decide_parameter_search_v1,
    materialize_parameter_proposals,
    only_deterministic_coarse_to_fine_implementation,
    plans_for_feedback_decision,
    verify_parameter_feedback_decision_occurrence,
)
from onlyalpha.research.search.parameter.context import OnlyParameterSearchContextResolver
from onlyalpha.research.search.symbolic import (
    SYMBOLIC_EVALUATION_CONTRACT_KIND,
    SYMBOLIC_PROPOSAL_KIND,
    SYMBOLIC_PROPOSAL_SCHEMA_VERSION,
    OnlyJsonSymbolicSearchStore,
    OnlySymbolicSearchContextResolver,
    build_symbolic_enumeration_result,
    commit_symbolic_enumeration_result_verified,
    enumerate_symbolic_factor_proposals,
)
from onlyalpha.runtime.generation import OnlyCoreExecutionIdentity, OnlyDistributionArtifactRole
from onlyalpha.strategy.qualification import (
    OnlyQualificationCriterion,
    OnlyQualificationEvaluator,
    OnlyQualificationEvidenceKind,
    OnlyQualificationEvidenceReference,
    OnlyQualificationGate,
    OnlyQualificationPolicyRevision,
)
from onlyalpha.strategy.qualification_store import (
    OnlyQualificationDecisionStore,
    OnlyQualificationPolicyStore,
    _only_compose_qualification_decision_authority,
)
from onlyalpha.strategy.store import OnlyFrozenStrategyRevisionStore
from tests.research.agent.test_decision_application_recovery import (
    derive_directive,
    tool_occurrence,
)
from tests.research.agent.test_decision_application_recovery import (
    service as agent_service,
)
from tests.research.evaluation.support import factor_pair_effect_case
from tests.research.postgres.test_postgres_authority import NOW, _authoring_provenance
from tests.research.search.symbolic.test_research_and_provenance_integration import (
    _fresh_process_e2e,
)
from tests.research.specification.support import registry as specification_registry
from tests.research.specification.support import specification
from tests.research.sweep.support import definition
from tests.runtime.search_ownership_support import _plain, _support_wheel


class _CandidateOwner:
    def __init__(self, candidate) -> None:  # type: ignore[no-untyped-def]
        self._candidate = candidate

    def load_verified(self, fingerprint: str):  # type: ignore[no-untyped-def]
        if fingerprint != self._candidate.candidate_fingerprint:
            raise LookupError(fingerprint)
        return self._candidate


def _stores(root: Path):  # type: ignore[no-untyped-def]
    layout = OnlyUserDataLayout(root)
    datasets = __import__(
        "onlyalpha.research.dataset.parquet_store", fromlist=["OnlyParquetResearchDatasetSnapshotStore"]
    ).OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    calculations = OnlyParquetResearchCalculationResultStore(layout.research_calculation_result_root, datasets)
    statistics = OnlyParquetResearchStatisticsResultStore(
        layout.research_statistics_result_root, calculations, audit_time=lambda: NOW
    )
    results = OnlyJsonResearchResultStore(layout.research_result_root, statistics, calculations)
    symbolic = OnlyJsonSymbolicSearchStore(root)
    parameter = OnlyJsonParameterSearchStore(root)
    return layout, datasets, calculations, statistics, results, symbolic, parameter


def _build_exact_runtime_generation(root: Path):  # type: ignore[no-untyped-def]
    package_names = (
        "onlyalpha",
        "onlyalpha-runtime-generation-manager",
        "onlyalpha-example-alpha",
        "onlyalpha-plugin-operators",
        "onlyalpha-plugin-indicators",
        "onlyalpha-plugin-targets",
        "numpy",
        "pyarrow",
        "pyyaml",
        "psycopg",
        "psycopg-binary",
    )
    wheels = {name: _support_wheel(name, root / "wheels") for name in package_names}
    core = _plain(wheels["onlyalpha"], "onlyalpha", OnlyDistributionArtifactRole.CORE)
    core_identity = OnlyCoreExecutionIdentity(core.distribution_name, core.distribution_version, core.artifact_sha256)
    providers = (operator_provider(), indicator_provider(), alpha_provider())
    catalog = OnlyQuantAssetCatalogGeneration(providers)
    quant_artifacts = tuple(
        only_quant_asset_distribution_artifact_manifest(
            source_repository=provider.manifest.distribution_name,
            source_revision="1" * 40,
            artifact_logical_name=wheels[provider.manifest.distribution_name].name,
            artifact_bytes=wheels[provider.manifest.distribution_name].read_bytes(),
            tested_core_execution_fingerprint=core_identity.fingerprint,
            provider=provider,
        )
        for provider in providers
    )
    target = wheels["onlyalpha-plugin-targets"]
    target_artifact = only_calculation_distribution_artifact_manifest(
        source_repository="OnlyAlpha",
        source_revision="1" * 40,
        distribution_name="onlyalpha-plugin-targets",
        distribution_version=metadata.version("onlyalpha-plugin-targets"),
        artifact_logical_name=target.name,
        artifact_bytes=target.read_bytes(),
        tested_core_execution_fingerprint=core_identity.fingerprint,
        registrations=target_registrations(),
    )
    artifacts = (
        core,
        _plain(
            wheels["onlyalpha-runtime-generation-manager"],
            "onlyalpha-runtime-generation-manager",
            OnlyDistributionArtifactRole.SUPPORT,
        ),
        target_artifact,
        *quant_artifacts,
        *(
            _plain(wheels[name], name, OnlyDistributionArtifactRole.SUPPORT)
            for name in ("numpy", "pyarrow", "pyyaml", "psycopg", "psycopg-binary")
        ),
    )
    store = OnlyLocalImmutableArtifactStore(root / "artifacts")
    content_by_name = {wheel.name: wheel.read_bytes() for wheel in wheels.values()}
    for artifact in artifacts:
        store.put_once(artifact, content_by_name[artifact.artifact_logical_name])
    builder = OnlyRuntimeGenerationBuilder(store, Path(sys.executable))
    validated = builder.build_validated(
        artifacts=artifacts,
        expected_catalog=catalog,
        environment_root=root / "build",
    )
    authority = OnlyRuntimeGenerationRegistry(root / "authority")
    authority.prepare(validated.manifest, actor="test-operator", occurred_at=NOW)
    authority.admit_ready(validated.validation_evidence, actor="test-validator", occurred_at=NOW)
    authority.activate_for_new_work(
        expected_current=None,
        target=validated.manifest.runtime_generation_fingerprint,
        actor="test-operator",
        occurred_at=NOW,
    )
    return authority, catalog, validated.manifest.runtime_generation_fingerprint


def _build_builder(
    root: Path,
    postgres_dsn: str,
    catalogs: OnlyRuntimeGenerationExactCatalogDescriptorReader,
    runtime_generations: OnlyRuntimeGenerationRegistry,
    authoring_generation_root: Path,
    pair_statistics,
    summary_statistics,
    search_catalogs=None,
) -> tuple[OnlyExperimentMemoryProductionBuilder, dict[str, object]]:
    layout, datasets, calculations, statistics, results, symbolic, parameter = _stores(root)
    search_catalogs = search_catalogs or _GenerationOwnedCatalogReader()
    contexts = _SearchContextReader(
        OnlySymbolicSearchContextResolver(
            symbolic_store=symbolic,
            catalogs=search_catalogs,
            datasets=datasets,
            research_calculation_registry=specification_registry(),
        ),
        OnlyParameterSearchContextResolver(
            parameter_store=parameter,
            evaluations=symbolic,
            catalogs=search_catalogs,
            datasets=datasets,
            research_calculation_registry=specification_registry(),
        ),
    )
    provenance = OnlyJsonSearchProvenanceStore(
        root,
        catalogs=search_catalogs,
        datasets=datasets,
        research_results=results,
        qualification_decisions=OnlyQualificationDecisionStore(root),
        freeze_relations=OnlyFrozenStrategyRevisionStore(root),
        search_contexts=contexts,
    )
    postgres = OnlyPostgresResearchSourceCutAuthority(postgres_dsn)
    sources = {
        "SEARCH_PROVENANCE": provenance,
        "AGENT_PROVENANCE": OnlyAgentProvenanceClosedCutAuthority(root),
        "RESEARCH_RESULT": results,
        "RESEARCH_STATISTICS": statistics,
        "RESEARCH_FACTOR_PAIR_STATISTICS": pair_statistics,
        "RESEARCH_SUMMARY_STATISTICS": summary_statistics,
        "QUALIFICATION_DECISION": OnlyQualificationDecisionStore(root),
        **{
            family: postgres.for_family(family)
            for family in (
                "RESEARCH_RUN",
                "RESEARCH_ATTEMPT",
                "PRODUCT_COMMAND_ADMISSION",
                "PRODUCT_COMMAND_RECEIPT",
            )
        },
    }
    references = OnlyExperimentMemoryReferenceReadersV1(
        datasets,
        catalogs,
        symbolic,
        parameter,
        calculations,
        runtime_generations,
        OnlyAuthoringExecutionGenerationStore(authoring_generation_root),
        OnlyQualificationPolicyStore(root),
        OnlyBacktestEvidenceStore(root),
    )
    builder = OnlyExperimentMemoryProductionBuilder(
        sources,
        references,
        OnlyExperimentMemoryRevisionStore(layout.experiment_memory_projection_root),
    )
    return builder, {
        "layout": layout,
        "datasets": datasets,
        "calculations": calculations,
        "statistics": statistics,
        "results": results,
        "symbolic": symbolic,
        "parameter": parameter,
        "provenance": provenance,
        "catalogs": catalogs,
        "search_catalogs": search_catalogs,
        "sources": sources,
        "references": references,
        "contexts": contexts,
    }


def _publish_parameter_experiment(root: Path, generation, values: dict[str, object]) -> None:
    symbolic = values["symbolic"]
    parameter = values["parameter"]
    provenance = values["provenance"]
    parameter_space = OnlyParameterFactorSearchSpaceV1.from_sweep(
        catalog_generation_fingerprint=generation.generation_fingerprint,
        sweep_definition=definition(values["dataset_fingerprint"]),
        candidate_template_node_id="momentum",
        candidate_output_name="factor_value",
        calculation_registry=specification_registry(),
    )
    from tests.research.search.parameter.test_adaptive_parameter_search_v1 import _policy

    policy = _policy()
    algorithm = only_deterministic_coarse_to_fine_implementation()
    evaluation = symbolic.load_evaluation_contract_intrinsic_verified(values["evaluation_fingerprint"])
    parameter.commit_search_space(parameter_space)
    parameter.commit_policy(policy)
    parameter.commit_algorithm_manifest(algorithm)
    proposals = materialize_parameter_proposals(parameter_space, specification_registry())
    for proposal in proposals:
        parameter.commit_proposal(proposal)
    experiment = OnlySearchExperimentManifestV3(
        OnlySearchHypothesisV1("bounded parameter topology certification"),
        OnlySearchAlgorithmBindingV1(
            algorithm.algorithm_id,
            algorithm.algorithm_semantic_version,
            algorithm.implementation_fingerprint,
            algorithm.source_revision,
        ),
        OnlySearchSpaceReferenceV1(PARAMETER_SEARCH_SPACE_KIND, 1, parameter_space.search_space_fingerprint),
        OnlySearchEvaluationContextReferenceV1(
            SYMBOLIC_EVALUATION_CONTRACT_KIND,
            evaluation.schema_version,
            evaluation.evaluation_contract_fingerprint,
        ),
        OnlySearchPolicyReferenceV1(PARAMETER_SEARCH_POLICY_KIND, 1, policy.policy_fingerprint),
        OnlySearchRandomnessMode.NONE,
        None,
        OnlySearchBudgetV1(2, 2, 1),
        generation.generation_fingerprint,
        values["dataset_fingerprint"],
        OnlySearchWorkflowBindingV1("parameter.factor.search", "1"),
        OnlySearchDecisionEngineBindingV1(OnlySearchDecisionMode.DETERMINISTIC),
    )
    provenance.commit_experiment(experiment)
    context = values["contexts"]._parameter.resolve_verified_context(experiment)
    decision = decide_parameter_search_v1(
        experiment_fingerprint=experiment.experiment_fingerprint,
        proposals=context.proposals,
        policy=context.policy,
        algorithm_implementation_fingerprint=context.historical_algorithm_manifest.implementation_fingerprint,
        budget=experiment.search_budget,
        evidence=(),
    )
    parameter.commit_feedback_decision(
        verify_parameter_feedback_decision_occurrence(
            context=context,
            provenance=provenance,
            evidence_reader=parameter,
            decisions=parameter,
            candidate_decision=decision,
        )
    )
    for plan in plans_for_feedback_decision(decision, context.proposals):
        provenance.commit_iteration_plan(plan)


def _publish_agent_facts(root: Path, experiment_fingerprint: str) -> None:
    fixture, context, models, tools, _decision_store, application = agent_service(root)
    resources = OnlyJsonAgentOrchestrationResourceStore(root)
    for resource in (
        context.workflow_resource,
        context.tool_policy_resource,
        *context.ordered_role_policy_resources,
        *context.supporting_resources,
    ):
        resources.commit_resource(resource)
    brief = OnlyJsonAgentResearchBriefStore(root, fixture.readers)
    brief.commit_research_brief(context.research_brief)
    OnlyJsonAgentSessionManifestStore(root, briefs=brief, resources=resources).commit_session_manifest(context.session)
    decision, _catalog_result = derive_directive(
        fixture,
        context,
        models,
        tools,
        application,
        __import__(
            "onlyalpha.research.agent", fromlist=["OnlyAgentRouterAction"]
        ).OnlyAgentRouterAction.SYMBOLIC_SEARCH,
    )
    submit_plan, submit_result = tool_occurrence(
        context,
        ordinal=1,
        decision=decision.decision_fingerprint,
        tool_class=__import__(
            "onlyalpha.research.agent", fromlist=["OnlyAgentToolClass"]
        ).OnlyAgentToolClass.SYMBOLIC_SEARCH,
        owner=OnlyAgentExactAuthorityReferenceV2(
            "SEARCH_EXPERIMENT", 1, OnlyAgentReferenceLocatorKind.SHA256, experiment_fingerprint
        ),
    )
    tools.add(submit_plan, submit_result)
    model_store = OnlyJsonAgentModelOccurrenceStore(root)
    tool_store = OnlyJsonAgentToolOccurrenceStore(root)
    for plan in models.plans:
        model_store.commit_plan(plan)
    for result in models.results.values():
        model_store.commit_result(result)
    for plan in tools.plans:
        tool_store.commit_plan(plan)
    for result in tools.results.values():
        tool_store.commit_result(result)
    from onlyalpha.research.agent.decision_store import OnlyJsonAgentExperimentLaunchStore

    OnlyJsonAgentExperimentLaunchStore(root).commit_launch_record(
        OnlyAgentExperimentLaunchRecordV1(
            context.session.session_fingerprint,
            decision.decision_fingerprint,
            submit_result.tool_call_result_fingerprint,
            experiment_fingerprint,
        )
    )


def _fresh_rebuild(
    root: Path,
    postgres_dsn: str,
    runtime_root: Path,
    authoring_root: Path,
    pair_root: Path,
    summary_root: Path,
) -> dict[str, object]:
    layout, datasets, calculations, statistics, results, _symbolic, _parameter = _stores(root)
    pair_dataset = OnlyParquetResearchDatasetSnapshotStore(pair_root / "datasets")
    pair_calculations = OnlyParquetResearchCalculationResultStore(pair_root / "calculation-results", pair_dataset)
    pair = OnlyParquetResearchFactorPairStatisticsResultStore(pair_root / "statistics-results", pair_calculations)
    summary = OnlyJsonResearchSummaryStatisticsResultStore(
        summary_root / "statistics-results", statistics, factor_pair_source_store=pair
    )
    runtime_generations = OnlyRuntimeGenerationRegistry(runtime_root / "authority")
    runtime_builder = OnlyRuntimeGenerationBuilder(
        OnlyLocalImmutableArtifactStore(runtime_root / "artifacts"), Path(sys.executable)
    )
    catalogs = OnlyRuntimeGenerationExactCatalogDescriptorReader(
        runtime_generations, runtime_builder, runtime_root / "catalog-context-cache"
    )
    builder, _ = _build_builder(
        root,
        postgres_dsn,
        catalogs,
        runtime_generations,
        authoring_root,
        pair,
        summary,
    )
    projection = builder.publish_and_activate(builder.capture_manifest())
    return {
        "manifest": projection.source_manifest.manifest_fingerprint,
        "records": [record.to_dict() for record in projection.records],
        "logical_digest": projection.logical_digest,
        "revision": projection.revision_fingerprint,
    }


@pytest.mark.integration
@pytest.mark.external
@pytest.mark.requires_network
@pytest.mark.postgres
@pytest.mark.recovery
def test_real_production_topology_closes_and_rebuilds_from_source_truth(postgres_dsn: str, tmp_path: Path) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    root = tmp_path / "user-data"
    pair_root = tmp_path / "pair"
    summary_root = tmp_path / "summary"
    runtime_root = tmp_path / "runtime-generations"
    authoring_root = tmp_path / "authoring-generations"

    runtime_generations, generation, runtime_fingerprint = _build_exact_runtime_generation(runtime_root)
    runtime_builder = OnlyRuntimeGenerationBuilder(
        OnlyLocalImmutableArtifactStore(runtime_root / "artifacts"), Path(sys.executable)
    )
    catalogs = OnlyRuntimeGenerationExactCatalogDescriptorReader(
        runtime_generations, runtime_builder, runtime_root / "catalog-context-cache"
    )

    chain = _fresh_process_e2e(root)
    layout, datasets, calculations, statistics, results, symbolic, _parameter = _stores(root)
    pair_case = factor_pair_effect_case(pair_root)
    pair_store = pair_case[10]
    pair_summary_store = OnlyJsonResearchSummaryStatisticsResultStore(
        summary_root / "statistics-results",
        statistics,
        factor_pair_source_store=pair_store,
        audit_time=lambda: NOW,
    )
    OnlyResearchFactorPairEffectSummaryExecutor(pair_store, pair_summary_store).execute(pair_case[13])
    pair_cut = pair_store.capture_closed_cut()
    summary_cut = pair_summary_store.capture_closed_cut()
    pair_payload = pair_store.iter_closed_cut_observations_verified(pair_cut.cut_fingerprint)[0].canonical_payload
    summary_payload = pair_summary_store.iter_closed_cut_observations_verified(summary_cut.cut_fingerprint)[
        0
    ].canonical_payload
    assert summary_payload["source_statistics_fingerprint"] == pair_payload["statistics_fingerprint"]
    assert summary_payload["source_statistics_result_fingerprint"] == pair_payload["statistics_result_fingerprint"]
    result = results.load_verified(chain["locator"])
    main_stats_fp = result.manifest.statistics_results[0].statistics_fingerprint
    main_stats = statistics.load_verified(main_stats_fp)
    summary_store = pair_summary_store

    builder, values = _build_builder(
        root,
        postgres_dsn,
        catalogs,
        runtime_generations,
        authoring_root,
        pair_store,
        summary_store,
        OnlyQuantAssetCatalogManager(generation),
    )
    values["dataset_fingerprint"] = result.manifest.dataset_snapshot_fingerprint
    experiment = values["provenance"].load_experiment_verified(chain["experiment"])
    values["evaluation_fingerprint"] = experiment.evaluation_context_reference.evaluation_fingerprint
    _publish_parameter_experiment(root, generation, values)
    _publish_agent_facts(root, chain["experiment"])

    provider = next(item for item in generation.providers if item.manifest.layer.value == "L3_FACTOR")
    authoring = _authoring_provenance()
    from onlyalpha.research.provenance import only_research_execution_generation_fingerprint

    provider_id = provider.manifest.provider_id
    provider_version = provider.manifest.provider_version
    provider_content_fingerprint = provider.content_fingerprint
    catalog_fingerprint = generation.generation_fingerprint
    authoring = replace(
        authoring,
        candidate_provider_id=provider_id,
        candidate_provider_version=provider_version,
        candidate_provider_content_fingerprint=provider_content_fingerprint,
        catalog_generation_fingerprint=catalog_fingerprint,
        execution_generation_fingerprint=only_research_execution_generation_fingerprint(
            experiment_id=authoring.experiment_id,
            source_repository=authoring.source_repository,
            source_revision=authoring.source_revision,
            source_tree=authoring.source_tree,
            candidate_provider_id=provider_id,
            candidate_provider_version=provider_version,
            candidate_provider_content_fingerprint=provider_content_fingerprint,
            catalog_generation_fingerprint=catalog_fingerprint,
        ),
    )
    OnlyAuthoringExecutionGenerationStore(authoring_root).commit(
        OnlyAuthoringExecutionGeneration(authoring, generation)
    )

    run_id = OnlyResearchRunId("00000000-0000-4000-8000-000000000931")
    run_spec = specification(result.manifest.dataset_snapshot_fingerprint)
    run = OnlyResearchRun.queued(
        run_id=run_id,
        specification=run_spec,
        canonical_specification_payload=__import__(
            "onlyalpha.canonical", fromlist=["only_canonical_json"]
        ).only_canonical_json(run_spec.to_dict()),
        admission_resolution_fingerprint="a" * 64,
        queued_at=NOW,
        authoring_provenance=authoring,
    )
    run_store = OnlyPostgresResearchRunStore(postgres_dsn)
    run_store.create_queued(run)
    runtime_generations.bind_work_exact(
        run_id.value,
        runtime_fingerprint,
        actor="topology-certifier",
        occurred_at=NOW,
    )
    from onlyalpha.application.product_command_receipt import (
        OnlyProductCommandAdmissionV1,
        OnlyProductCommandId,
        OnlyProductCommandKind,
        OnlyProductCommandOutcomeKind,
        OnlyProductCommandOutcomeRef,
        OnlyProductCommandReceipt,
    )

    command_id = OnlyProductCommandId("00000000-0000-4000-8000-000000000932")
    command_fingerprint = "b" * 64
    product = OnlyPostgresProductCommandAuthority(postgres_dsn)
    product.admit_exact(
        OnlyProductCommandAdmissionV1(command_id, OnlyProductCommandKind.CREATE_RESEARCH_RUN, command_fingerprint)
    )
    product.put_verified_receipt(
        OnlyProductCommandReceipt(
            command_id,
            OnlyProductCommandKind.CREATE_RESEARCH_RUN,
            command_fingerprint,
            OnlyProductCommandOutcomeRef(OnlyProductCommandOutcomeKind.RESEARCH_RUN, run_id.value),
            NOW,
        )
    )
    execution_store = OnlyPostgresResearchExecutionStore(
        postgres_dsn, authoring_execution_generation_fingerprint=authoring.execution_generation_fingerprint
    )
    claim = execution_store.claim_next(
        worker_instance_id=__import__(
            "onlyalpha.research.execution", fromlist=["OnlyResearchWorkerInstanceId"]
        ).OnlyResearchWorkerInstanceId("00000000-0000-4000-8000-000000000933"),
        attempt_id=__import__(
            "onlyalpha.research.execution", fromlist=["OnlyResearchRunAttemptId"]
        ).OnlyResearchRunAttemptId("00000000-0000-4000-8000-000000000934"),
        lease_duration=timedelta(minutes=2),
        max_attempts=3,
        run_started_at=NOW + timedelta(seconds=1),
    )
    assert claim is not None
    completed = execution_store.complete(
        claim=claim,
        run_finished_at=NOW + timedelta(seconds=2),
        research_result_fingerprint=chain["research"],
        artifact_content_fingerprint="c" * 64,
        calculation_execution_evidence_fingerprints=("d" * 64,),
    )
    assert completed.state is OnlyResearchRunState.COMPLETED

    policies = OnlyQualificationPolicyStore(root)
    backtest_policy = OnlyQualificationPolicyRevision(
        "topology-backtest-gate",
        "1",
        OnlyQualificationGate.BACKTEST_TO_SIM,
        (
            OnlyQualificationCriterion(
                "artifact",
                OnlyQualificationEvidenceKind.BACKTEST_EVIDENCE,
                "backtest.artifact_count",
                "GE",
                __import__("decimal").Decimal(1),
            ),
        ),
    )
    policies.put(backtest_policy)
    strategy_fp = next((root / "strategy/frozen-revisions/sha256").glob("*/*")).name
    artifact = b"topology-certification"
    evidence = OnlyBacktestEvidenceManifest(
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        run_spec.specification_fingerprint,
        "e" * 64,
        strategy_fp,
        result.manifest.dataset_snapshot_fingerprint,
        result.manifest.dataset_snapshot_fingerprint,
        "f" * 64,
        "1" * 64,
        "2" * 64,
        "3" * 64,
        "kernel-v1",
        ("4" * 64,),
        "5" * 64,
        "6" * 64,
        (("result.txt", hashlib.sha256(artifact).hexdigest(), len(artifact), "text/plain"),),
    )
    evidence = OnlyBacktestEvidenceStore(root).publish(evidence, {"result.txt": artifact})
    decisions, publisher = _only_compose_qualification_decision_authority(root)
    OnlyQualificationEvaluator(
        strategies=OnlyFrozenStrategyRevisionStore(root),
        policies=policies,
        research_results=results,
        backtest_evidence=OnlyBacktestEvidenceStore(root),
        decisions=publisher,
    ).evaluate(
        subject_strategy_fingerprint=strategy_fp,
        policy_id=backtest_policy.policy_id,
        policy_version=backtest_policy.policy_version,
        evidence=(
            OnlyQualificationEvidenceReference(
                OnlyQualificationEvidenceKind.BACKTEST_EVIDENCE, evidence.evidence_fingerprint
            ),
        ),
    )

    manifest = builder.capture_manifest()
    assert set(manifest.to_dict()["cuts"][0]) == {
        "source_family",
        "source_schema_version",
        "enumeration_contract_version",
        "cut_fingerprint",
        "cut_boundary",
        "completeness_proof",
    }
    assert all(
        len(builder._sources[family].load_closed_cut_verified(cut.cut_fingerprint).entries) > 0
        for family, cut in ((cut.source_family, cut) for cut in manifest.cuts)
    )
    initial = builder.publish_and_activate(manifest)
    source_snapshot = tuple(
        (
            cut.source_family,
            cut.cut_fingerprint,
            tuple(
                entry.to_dict().items()
                for entry in builder._sources[cut.source_family].load_closed_cut_verified(cut.cut_fingerprint).entries
            ),
        )
        for cut in manifest.cuts
    )
    with psycopg.connect(postgres_dsn) as connection:
        postgres_snapshot = (
            connection.execute(
                "SELECT last_index FROM research_source_history_frontier WHERE singleton = TRUE"
            ).fetchone()[0],
            tuple(
                connection.execute(
                    "SELECT event_index, source_family, native_locator, source_row, operation, schema_version "
                    "FROM research_source_history ORDER BY event_index"
                ).fetchall()
            ),
        )
    projection_root = layout.experiment_memory_projection_root
    shutil.rmtree(projection_root)
    script = (
        "import json,sys; from pathlib import Path; "
        "from tests.research.postgres.test_memory_production_topology_certification import _fresh_rebuild; "
        "value=_fresh_rebuild(Path(sys.argv[1]),sys.argv[2],Path(sys.argv[3]),Path(sys.argv[4]),Path(sys.argv[5]),Path(sys.argv[6])); print(json.dumps(value,sort_keys=True))"
    )
    rebuilt = json.loads(
        subprocess.check_output(
            [
                sys.executable,
                "-c",
                script,
                str(root),
                postgres_dsn,
                str(runtime_root),
                str(authoring_root),
                str(pair_root),
                str(summary_root),
            ],
            text=True,
        )
    )
    assert rebuilt["manifest"] == initial.source_manifest.manifest_fingerprint
    assert rebuilt["records"] == [record.to_dict() for record in initial.records]
    assert rebuilt["logical_digest"] == initial.logical_digest
    assert rebuilt["revision"] == initial.revision_fingerprint
    assert source_snapshot == tuple(
        (
            cut.source_family,
            cut.cut_fingerprint,
            tuple(
                entry.to_dict().items()
                for entry in builder._sources[cut.source_family].load_closed_cut_verified(cut.cut_fingerprint).entries
            ),
        )
        for cut in manifest.cuts
    )
    with psycopg.connect(postgres_dsn) as connection:
        assert postgres_snapshot == (
            connection.execute(
                "SELECT last_index FROM research_source_history_frontier WHERE singleton = TRUE"
            ).fetchone()[0],
            tuple(
                connection.execute(
                    "SELECT event_index, source_family, native_locator, source_row, operation, schema_version "
                    "FROM research_source_history ORDER BY event_index"
                ).fetchall()
            ),
        )

    new_result_stats_plan = replace(
        main_stats.manifest.plan,
        definition=replace(main_stats.manifest.plan.definition, method=OnlyResearchStatisticsMethod.RANK_IC),
    )
    new_stats = OnlyResearchStatisticsExecutor(calculations, statistics).execute(new_result_stats_plan)
    candidate = replace(result.manifest.plan.candidates[0], statistics_fingerprints=(new_stats.statistics_fingerprint,))
    new_plan = replace(
        result.manifest.plan, statistics_fingerprints=(new_stats.statistics_fingerprint,), candidates=(candidate,)
    )
    new_result = OnlyResearchResultAssembler(
        statistics, audit_time=lambda: datetime(2026, 9, 14, tzinfo=UTC), calculation_result_store=calculations
    ).assemble(new_plan)
    results.commit(new_result)
    child = replace(
        experiment,
        hypothesis=OnlySearchHypothesisV1("out-of-cut child"),
        parent_experiment_fingerprint=experiment.experiment_fingerprint,
    )
    contexts = values["provenance"]
    contexts.commit_experiment(child)
    child_context_resolver = OnlySymbolicSearchContextResolver(
        symbolic_store=symbolic,
        catalogs=values["search_catalogs"],
        datasets=values["datasets"],
        research_calculation_registry=specification_registry(),
    )
    child_context = child_context_resolver.resolve_verified_context(child)
    child_enumeration = enumerate_symbolic_factor_proposals(
        child_context.verified_search_space, proposal_limit=child.search_budget.proposal_limit
    )
    for child_proposal in child_enumeration.proposals:
        symbolic.commit_proposal(child_proposal)
    commit_symbolic_enumeration_result_verified(
        build_symbolic_enumeration_result(child, child_enumeration), child_context, symbolic
    )
    proposal = child_enumeration.proposals[0]
    child_plan = OnlySearchIterationPlanV1(
        child.experiment_fingerprint,
        0,
        SYMBOLIC_PROPOSAL_KIND,
        SYMBOLIC_PROPOSAL_SCHEMA_VERSION,
        proposal.proposal_fingerprint,
        (),
        (),
        proposal.proposal_fingerprint,
    )
    contexts.commit_iteration_plan(child_plan)
    contexts.commit_iteration_result(
        OnlySearchIterationResultV1(
            child_plan.iteration_plan_fingerprint,
            candidate.candidate_fingerprint,
            True,
            OnlySearchResearchResultReferenceV1(
                new_result.manifest.research_result_plan_fingerprint, new_result.manifest.research_result_fingerprint
            ),
            False,
            None,
            __import__(
                "onlyalpha.research.experiment", fromlist=["OnlySearchIterationDisposition"]
            ).OnlySearchIterationDisposition.RESEARCH_EVIDENCE_RECORDED,
            None,
        )
    )
    new_search_cut = values["sources"]["SEARCH_PROVENANCE"].capture_closed_cut()
    old_cuts = [
        builder._sources[cut.source_family].load_closed_cut_verified(cut.cut_fingerprint) for cut in manifest.cuts
    ]
    mixed = OnlyExperimentMemorySourceCutManifestV1.from_cuts(
        [new_search_cut if cut.source_family == "SEARCH_PROVENANCE" else cut for cut in old_cuts]
    )
    with pytest.raises(OnlyMemoryProjectionError, match="CROSS_SOURCE_CLOSURE_INCOMPLETE"):
        builder.build(mixed)
    assert builder._revisions.load_active_verified().revision_fingerprint == initial.revision_fingerprint
    missing_builder, _ = _build_builder(
        root,
        postgres_dsn,
        OnlyRuntimeGenerationExactCatalogDescriptorReader(
            OnlyRuntimeGenerationRegistry(tmp_path / "missing-runtime-generations"),
            runtime_builder,
            tmp_path / "missing-catalog-context",
        ),
        runtime_generations,
        authoring_root,
        pair_store,
        summary_store,
    )
    with pytest.raises(OnlyMemoryProjectionError, match="REFERENCE_AUTHORITY_UNAVAILABLE"):
        missing_builder.build(manifest)
    assert (
        OnlyExperimentMemoryRevisionStore(projection_root).load_active_verified().revision_fingerprint
        == initial.revision_fingerprint
    )
