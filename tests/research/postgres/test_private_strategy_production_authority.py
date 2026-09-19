from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from onlyalpha_authoring_execution_worker import (
    OnlyAuthoringExecutionGeneration,
    OnlyAuthoringExecutionGenerationStore,
    OnlyVerifiedAuthoringGenerationReader,
)

from onlyalpha.application import (
    OnlyCalculationEquivalenceCertificationApplicationService,
    OnlyProductCommandId,
)
from onlyalpha.application.private_strategy_research import OnlyPrivateStrategyResearchApplicationService
from onlyalpha.application.product_boundary import (
    OnlySubmitPrivateStrategyResearch,
    only_compose_research_product_boundary,
)
from onlyalpha.application.strategy_authority import OnlyStrategyFreezeApplicationService
from onlyalpha.calculation import (
    OnlyCalculationEquivalenceEvidenceV2Store,
    OnlyCalculationKind,
    OnlyCalculationTypeReference,
)
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBarType
from onlyalpha.kernel import OnlyAlphaKernelHost
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.persistence.postgres import (
    OnlyPostgresPrivateAssetStore,
    OnlyPostgresPrivateStrategyResearchCompositionStore,
    OnlyPostgresProductCommandAuthority,
    OnlyPostgresResearchDeploymentStore,
    OnlyPostgresResearchExecutionStore,
    OnlyPostgresResearchRunStore,
)
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.quant_assets import (
    OnlyPrivateAssetExampleImporterV1,
    OnlyPrivateAssetKind,
    OnlyPrivateAssetRevisionBindingResolver,
    OnlyPrivateAssetRevisionReferenceV1,
    OnlyPrivateFactorExecutableClosureV1,
    OnlyPrivateFactorIsolatedProgramHost,
    OnlyPrivateStrategyResearchComposer,
    OnlyPrivateStrategyResearchCompositionError,
    OnlyPrivateStrategyResearchCompositionVerifier,
    OnlyPrivateStrategyResearchContextV1,
    only_discover_quant_asset_providers,
    only_load_private_asset_example_bundle,
)
from onlyalpha.research.calculation.execution_evidence import OnlyResearchCalculationExecutionEvidenceStore
from onlyalpha.research.calculation.result_store import OnlyParquetResearchCalculationResultStore
from onlyalpha.research.command.model import only_novelty_gated_research_run_id
from onlyalpha.research.command.query import OnlyResearchRunQueryService
from onlyalpha.research.command.service import OnlyResearchCommandService
from onlyalpha.research.dataset import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.definition import (
    OnlyResearchCalculationInput,
    OnlyResearchCalculationInstance,
    OnlyResearchFixedParameter,
    OnlyResearchStatisticsRequest,
    OnlyResearchVariableRef,
)
from onlyalpha.research.definition.resolver import OnlyResearchDefinitionResolver
from onlyalpha.research.evaluation import OnlyExactEvaluationIntentResolverV1
from onlyalpha.research.evaluation.definition import OnlyResearchStatisticsDefinition, OnlyResearchStatisticsMethod
from onlyalpha.research.evaluation.result_store import OnlyParquetResearchStatisticsResultStore
from onlyalpha.research.execution import (
    OnlyEngineResearchRuntimeExecutor,
    OnlyResearchExecutionPolicy,
    OnlyResearchRunAttemptId,
    OnlyResearchWorker,
    OnlyResearchWorkerInstanceId,
)
from onlyalpha.research.memory.projector import OnlyExperimentMemoryProjectionV1
from onlyalpha.research.memory.source_manifest import MANDATORY_FAMILIES, OnlyExperimentMemorySourceCutManifestV1
from onlyalpha.research.memory.store import OnlyExperimentMemoryRevisionStore
from onlyalpha.research.novelty import (
    OnlyNoveltyDecisionAuthority,
    OnlyNoveltyDecisionRequestV2,
    OnlyNoveltyPolicyStore,
)
from onlyalpha.research.operations.deployment import OnlyResearchSemanticStoreIdentity
from onlyalpha.research.result.result_store import OnlyJsonResearchResultStore
from onlyalpha.research.run.admission import OnlyResearchRunAdmissionService
from onlyalpha.research.run.evidence import OnlyResearchAdmissionResolutionEvidence
from onlyalpha.research.source_cut import OnlySourceClosedCutV1
from onlyalpha.research.specification import OnlyResearchSpecificationResolver
from onlyalpha.runtime.trading.predicate import only_register_trading_predicate_primitives
from onlyalpha.strategy.freeze import OnlyStrategyFreezeRequest
from onlyalpha.strategy.store import OnlyFrozenStrategyRevisionStore
from tests.research.calculation.support import bars, snapshot
from tests.research.novelty.test_policy import policy
from tests.runtime_support.generation_support import OnlyTestRuntimeGenerationAuthority

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]

NOW = datetime(2026, 9, 1, 1, 2, 3, tzinfo=UTC)


class _Datasets:
    def __init__(self, store: OnlyParquetResearchDatasetSnapshotStore, fingerprint: str) -> None:
        self._store = store
        self._fingerprint = fingerprint

    def resolve_verified(self, expected):  # type: ignore[no-untyped-def]
        verified = self._store.load_verified_table(self._fingerprint)
        if verified.snapshot.definition != expected:
            raise ValueError("Dataset Definition is unavailable")
        return verified


def _simple_momentum_context() -> OnlyPrivateStrategyResearchContextV1:
    target = OnlyResearchCalculationInstance(
        "forward_return",
        OnlyCalculationTypeReference(OnlyCalculationKind.TARGET, "onlyalpha.target.forward_return", "1"),
        {"exit_offset": OnlyResearchFixedParameter(1)},
        ("target_value",),
        (
            OnlyResearchCalculationInput("entry_price", "bar.close"),
            OnlyResearchCalculationInput("exit_price", "bar.close"),
        ),
    )
    statistics = OnlyResearchStatisticsRequest(
        OnlyResearchVariableRef("momentum", "value"),
        "forward_return",
        OnlyResearchStatisticsDefinition(method=OnlyResearchStatisticsMethod.IC),
    )
    return OnlyPrivateStrategyResearchContextV1(
        "2026-01-05T01:30:00+00:00",
        "2026-01-05T01:34:01+00:00",
        (target,),
        (statistics,),
    )


def _test_xshg_snapshot():  # type: ignore[no-untyped-def]
    instrument = OnlyInstrumentId.parse("TEST.XSHG")
    values = tuple(
        replace(
            item,
            bar_type=OnlyBarType(instrument, item.bar_type.specification, item.bar_type.aggregation_source),
        )
        for item in bars()
        if str(item.instrument_id) == "A.XNAS"
    )
    return snapshot(values)


def _generation(
    assets: OnlyPostgresPrivateAssetStore,
    factor_reference,
    root: Path,
    *,
    provider_id: str,
) -> tuple[OnlyAuthoringExecutionGeneration, OnlyVerifiedAuthoringGenerationReader]:  # type: ignore[no-untyped-def]
    factor = assets.load_factor_revision(
        factor_reference.private_asset_id,
        factor_reference.private_asset_revision_fingerprint,
    )
    closure = OnlyPrivateFactorExecutableClosureV1.create(
        factor,
        ({"close": Decimal("2"), "previous_close": Decimal("1")},),
        {},
        host=OnlyPrivateFactorIsolatedProgramHost(3),
    )
    generation = OnlyAuthoringExecutionGeneration.create_verified(
        experiment_id="exp-" + only_canonical_fingerprint(provider_id)[:32],
        private_asset_revision_reference=OnlyPrivateAssetRevisionReferenceV1(
            OnlyPrivateAssetKind.FACTOR,
            factor.factor_id,
            factor.revision_fingerprint,
        ),
        private_asset_revisions=OnlyPrivateAssetRevisionBindingResolver(assets),
        private_factor_executable_closure=closure,
        candidate_provider_id=provider_id,
        base_catalog=only_discover_quant_asset_providers(),
    )
    store = OnlyAuthoringExecutionGenerationStore(root)
    store.commit(generation)
    return generation, OnlyVerifiedAuthoringGenerationReader(
        store,
        OnlyPrivateAssetRevisionBindingResolver(assets),
    )


def _memory_manifest() -> OnlyExperimentMemorySourceCutManifestV1:
    postgres_families = {
        "RESEARCH_RUN",
        "RESEARCH_ATTEMPT",
        "PRODUCT_COMMAND_ADMISSION",
        "PRODUCT_COMMAND_RECEIPT",
    }
    return OnlyExperimentMemorySourceCutManifestV1.from_cuts(
        tuple(
            OnlySourceClosedCutV1(
                family,
                1,
                (),
                "JOURNAL_INDEX:0" if family in postgres_families else "TC1_CLOSED_CUT_V1",
                "SOURCE_TRANSACTIONAL_JOURNAL_V1" if family in postgres_families else "TC1_COMPLETE_V1",
            )
            for family in MANDATORY_FAMILIES
        )
    )


class _MemoryBuilder:
    def __init__(self, revisions: OnlyExperimentMemoryRevisionStore) -> None:
        self._revisions = revisions
        self._manifest = _memory_manifest()

    def capture_manifest(self) -> OnlyExperimentMemorySourceCutManifestV1:
        return self._manifest

    def publish_and_activate(self, manifest: OnlyExperimentMemorySourceCutManifestV1) -> object:
        fingerprint = self._revisions._publish_and_activate(OnlyExperimentMemoryProjectionV1(manifest, ()))
        return self._revisions.load_verified(fingerprint)


def test_private_strategy_production_chain_is_exact_and_generation_bound(postgres_dsn: str, tmp_path: Path) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    assets = OnlyPostgresPrivateAssetStore(postgres_dsn)
    imported = OnlyPrivateAssetExampleImporterV1(assets).import_bundles(
        (
            only_load_private_asset_example_bundle(Path("examples/private-assets/factor/simple_momentum")),
            only_load_private_asset_example_bundle(Path("examples/private-assets/strategy/simple_momentum")),
        )
    )
    factor_reference = imported["factor.simple_momentum"]
    strategy_reference = imported["strategy.simple_momentum"]
    generation, authoring = _generation(
        assets,
        factor_reference,
        tmp_path / "authoring-generations",
        provider_id="candidate.private.simple_momentum.g1",
    )
    generation_two, authoring_two = _generation(
        assets,
        factor_reference,
        tmp_path / "authoring-generations",
        provider_id="candidate.private.simple_momentum.g2",
    )
    assert generation.catalog.generation_fingerprint != generation_two.catalog.generation_fingerprint

    layout = OnlyUserDataLayout(tmp_path / "user-data")
    semantic_root = layout.research_root
    namespace = OnlyResearchSemanticStoreIdentity(semantic_root).initialize()
    dataset_store = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    dataset, partitions = _test_xshg_snapshot()
    dataset_store.commit(dataset, partitions)
    context = _simple_momentum_context()
    exact_calculations = authoring.load_calculation_registry_verified(generation.fingerprint)
    exact_calculations_two = authoring_two.load_calculation_registry_verified(generation_two.fingerprint)
    definition_resolver = OnlyResearchDefinitionResolver(
        exact_calculations,
        _Datasets(dataset_store, dataset.snapshot_fingerprint),
    )
    definition_resolver_two = OnlyResearchDefinitionResolver(
        exact_calculations_two,
        _Datasets(dataset_store, dataset.snapshot_fingerprint),
    )
    run_store = OnlyPostgresResearchRunStore(postgres_dsn)
    submission_key = OnlyProductCommandId("00000000-0000-4000-8000-000000000952")
    runtime_generations = OnlyTestRuntimeGenerationAuthority(
        generation.fingerprint,
        generation.provenance.catalog_generation_fingerprint,
    )
    preview = OnlyPrivateStrategyResearchComposer(assets, generation.catalog).compose(strategy_reference, context)
    preview_two = OnlyPrivateStrategyResearchComposer(assets, generation_two.catalog).compose(
        strategy_reference, context
    )
    assert preview.research_definition == preview_two.research_definition
    expected_run_id = only_novelty_gated_research_run_id(submission_key)
    runtime_generations.bind_work_exact(expected_run_id.value, generation.fingerprint)

    class _ExactRuntimeAdmissionResolver:
        def __init__(self) -> None:
            self._resolvers = {
                generation.fingerprint: OnlyResearchSpecificationResolver(exact_calculations),
                generation_two.fingerprint: OnlyResearchSpecificationResolver(exact_calculations_two),
            }

        def resolve(self, fingerprint: str, specification):  # type: ignore[no-untyped-def]
            resolver = self._resolvers.get(fingerprint)
            if resolver is None:
                raise ValueError("RUNTIME_GENERATION_NOT_FOUND")
            resolution = resolver.resolve(specification)
            return OnlyResearchAdmissionResolutionEvidence.from_resolution(resolution)

    runtime_resolution = _ExactRuntimeAdmissionResolver()
    subject = OnlyExactEvaluationIntentResolverV1(
        runtime_generations=runtime_generations,
        runtime_resolution=runtime_resolution,
        authoring_generations=authoring,
    ).resolve(
        definition_resolver.resolve(preview.research_definition).specification,
        runtime_work_id=expected_run_id.value,
        authoring_generation_fingerprint=generation.fingerprint,
    )
    memory_revisions = OnlyExperimentMemoryRevisionStore(layout.experiment_memory_projection_root)
    initial_memory = OnlyExperimentMemoryProjectionV1(_memory_manifest(), ())
    memory_revisions._publish_and_activate(initial_memory)
    novelty_policies = OnlyNoveltyPolicyStore(layout.research_root)
    novelty_policies.put(policy())
    novelty_decisions = OnlyNoveltyDecisionAuthority(layout.research_root)
    novelty_decisions.seal_from_request(
        OnlyNoveltyDecisionRequestV2(
            submission_key,
            "default-novelty",
            "1",
            subject,
        ),
        initial_memory.revision_fingerprint,
        memory_revisions,
        novelty_policies,
    )
    product_commands = OnlyPostgresProductCommandAuthority(postgres_dsn)
    admission = OnlyResearchRunAdmissionService(
        resolver=OnlyResearchSpecificationResolver(exact_calculations),
        dataset_store=dataset_store,
        now_utc=lambda: NOW,
        authoring_generation_resolver=authoring,
    )
    command = OnlyResearchCommandService(
        admission=admission,
        store=run_store,
        now_utc=lambda: NOW,
        runtime_generations=runtime_generations,
        authoring_generation_reader=authoring,
        command_admissions=product_commands,
        runtime_generation_resolver=runtime_resolution,
        novelty_decisions=novelty_decisions,
        memory_builder=_MemoryBuilder(memory_revisions),
        memory_revisions=memory_revisions,
    )
    compositions = OnlyPostgresPrivateStrategyResearchCompositionStore(postgres_dsn)
    strategy_research = OnlyPrivateStrategyResearchApplicationService(
        composer=OnlyPrivateStrategyResearchComposer(assets, generation.catalog),
        compositions=compositions,
        definitions=definition_resolver,
        research=command,
        authoring_generations=authoring,
    )
    kernel = OnlyAlphaKernelHost()
    kernel.start()
    try:
        product = only_compose_research_product_boundary(
            admission=kernel,
            commands=command,
            queries=OnlyResearchRunQueryService(run_store),
            strategy_research=strategy_research,
        )
        outcome = product.submit_private_strategy_research(
            OnlySubmitPrivateStrategyResearch(
                submission_key=submission_key,
                strategy_revision=strategy_reference,
                research_context=context,
                authoring_generation_fingerprint=generation.fingerprint,
            )
        )
    finally:
        kernel.stop()

    composition = compositions.load(outcome.run.strategy_research_composition_fingerprint or "")
    assert composition.catalog_generation_fingerprint == generation.provenance.catalog_generation_fingerprint
    assert outcome.run.authoring_generation_fingerprint == generation.fingerprint
    restarted_compositions = OnlyPostgresPrivateStrategyResearchCompositionStore(postgres_dsn)
    assert restarted_compositions.load(composition.composition_fingerprint) == composition
    assert restarted_compositions.load_context(composition.composition_fingerprint) == context

    execution_store = OnlyPostgresResearchExecutionStore(
        postgres_dsn,
        authoring_execution_generation_fingerprint=generation.fingerprint,
    )
    claim = execution_store.claim_next(
        worker_instance_id=OnlyResearchWorkerInstanceId("00000000-0000-4000-8000-000000000953"),
        attempt_id=OnlyResearchRunAttemptId("00000000-0000-4000-8000-000000000954"),
        lease_duration=timedelta(minutes=2),
        max_attempts=1,
        run_started_at=NOW + timedelta(seconds=1),
        eligible_run_ids=(outcome.run.run_id.value,),
    )
    assert claim is not None
    worker = OnlyResearchWorker(
        worker_instance_id=claim.attempt.worker_instance_id,
        execution_store=execution_store,
        run_store=OnlyPostgresResearchRunStore(postgres_dsn),
        resolver=OnlyResearchSpecificationResolver(exact_calculations),
        dataset_store=dataset_store,
        runtime_executor=OnlyEngineResearchRuntimeExecutor(layout.root, generation.engine_services()),
        policy=OnlyResearchExecutionPolicy(max_attempts=1),
        now_utc=lambda: NOW + timedelta(seconds=2),
        runtime_generations=runtime_generations,
        process_generation_fingerprint=runtime_generations.generation_fingerprint,
        authoring_execution_generation_fingerprint=generation.fingerprint,
    )
    execution = worker.execute_claim(claim)
    assert execution.run is not None and execution.run.state.value == "COMPLETED"
    completed = OnlyPostgresResearchRunStore(postgres_dsn).load(outcome.run.run_id)
    assert completed.strategy_research_composition_fingerprint == composition.composition_fingerprint
    assert completed.authoring_generation_fingerprint == generation.fingerprint
    assert completed.calculation_execution_evidence_fingerprints

    verifier = OnlyPrivateStrategyResearchCompositionVerifier(
        OnlyPrivateStrategyResearchComposer(assets, generation.catalog),
        restarted_compositions,
        definition_resolver,
        authoring_generations=authoring,
        execution_evidence=OnlyResearchCalculationExecutionEvidenceStore(layout.research_root),
    )
    verifier.verify(completed)
    evidence_store = OnlyResearchCalculationExecutionEvidenceStore(layout.research_root)
    assert all(
        evidence_store.load_verified(item).research_implementation_bindings
        and evidence_store.load_verified(item).authoring_generation_fingerprint == generation.fingerprint
        for item in completed.calculation_execution_evidence_fingerprints
    )

    submission_key_two = OnlyProductCommandId("00000000-0000-4000-8000-000000000955")
    expected_run_id_two = only_novelty_gated_research_run_id(submission_key_two)
    runtime_generations.activate(
        generation_two.fingerprint,
        catalog_generation_fingerprint=generation_two.provenance.catalog_generation_fingerprint,
    )
    runtime_generations.bind_work_exact(expected_run_id_two.value, generation_two.fingerprint)
    subject_two = OnlyExactEvaluationIntentResolverV1(
        runtime_generations=runtime_generations,
        runtime_resolution=runtime_resolution,
        authoring_generations=authoring_two,
    ).resolve(
        definition_resolver_two.resolve(preview_two.research_definition).specification,
        runtime_work_id=expected_run_id_two.value,
        authoring_generation_fingerprint=generation_two.fingerprint,
    )
    novelty_decisions.seal_from_request(
        OnlyNoveltyDecisionRequestV2(
            submission_key_two,
            "default-novelty",
            "1",
            subject_two,
        ),
        memory_revisions.load_active_verified().revision_fingerprint,
        memory_revisions,
        novelty_policies,
    )
    command_two = OnlyResearchCommandService(
        admission=OnlyResearchRunAdmissionService(
            resolver=OnlyResearchSpecificationResolver(exact_calculations_two),
            dataset_store=dataset_store,
            now_utc=lambda: NOW,
            authoring_generation_resolver=authoring_two,
        ),
        store=OnlyPostgresResearchRunStore(postgres_dsn),
        now_utc=lambda: NOW,
        runtime_generations=runtime_generations,
        command_admissions=product_commands,
        runtime_generation_resolver=runtime_resolution,
        authoring_generation_reader=authoring_two,
        novelty_decisions=novelty_decisions,
        memory_builder=_MemoryBuilder(memory_revisions),
        memory_revisions=memory_revisions,
    )
    drifted = command_two.submit_research_run(
        submission_key_two,
        definition_resolver.resolve(preview.research_definition).specification,
        generation_two.fingerprint,
        strategy_research_composition_fingerprint=composition.composition_fingerprint,
    )
    execution_store_two = OnlyPostgresResearchExecutionStore(
        postgres_dsn,
        authoring_execution_generation_fingerprint=generation_two.fingerprint,
    )
    claim_two = execution_store_two.claim_next(
        worker_instance_id=OnlyResearchWorkerInstanceId("00000000-0000-4000-8000-000000000956"),
        attempt_id=OnlyResearchRunAttemptId("00000000-0000-4000-8000-000000000957"),
        lease_duration=timedelta(minutes=2),
        max_attempts=1,
        run_started_at=NOW + timedelta(seconds=4),
        eligible_run_ids=(drifted.run.run_id.value,),
    )
    assert claim_two is not None
    execution_two = OnlyResearchWorker(
        worker_instance_id=claim_two.attempt.worker_instance_id,
        execution_store=execution_store_two,
        run_store=OnlyPostgresResearchRunStore(postgres_dsn),
        resolver=OnlyResearchSpecificationResolver(exact_calculations_two),
        dataset_store=dataset_store,
        runtime_executor=OnlyEngineResearchRuntimeExecutor(layout.root, generation_two.engine_services()),
        policy=OnlyResearchExecutionPolicy(max_attempts=1),
        now_utc=lambda: NOW + timedelta(seconds=5),
        runtime_generations=runtime_generations,
        process_generation_fingerprint=generation_two.fingerprint,
        authoring_execution_generation_fingerprint=generation_two.fingerprint,
    ).execute_claim(claim_two)
    assert execution_two.run is not None and execution_two.run.state.value == "COMPLETED"
    completed_two = OnlyPostgresResearchRunStore(postgres_dsn).load(drifted.run.run_id)
    assert completed_two.authoring_generation_fingerprint == generation_two.fingerprint
    assert completed_two.calculation_execution_evidence_fingerprints
    with pytest.raises(OnlyPrivateStrategyResearchCompositionError, match="Composition execution context differs"):
        verifier.verify(completed_two)

    OnlyPostgresResearchDeploymentStore(postgres_dsn).initialize(namespace)
    calculation_results = OnlyParquetResearchCalculationResultStore(
        layout.research_calculation_result_root, dataset_store
    )
    statistics_results = OnlyParquetResearchStatisticsResultStore(
        layout.research_statistics_result_root,
        calculation_results,
    )
    results = OnlyJsonResearchResultStore(
        layout.research_result_root,
        statistics_results,
        calculation_results,
    )
    exact_specification = authoring.resolve(generation.fingerprint, completed.specification)
    only_register_trading_predicate_primitives(exact_calculations)
    decision_candidate = next(item for item in exact_specification.candidates if item.calculation_id == "decision")
    certification = OnlyCalculationEquivalenceCertificationApplicationService(
        exact_calculations,
        OnlyCalculationEquivalenceEvidenceV2Store(semantic_root),
    )
    for node in decision_candidate.graph.nodes:
        certification.certify(node)
    freeze = OnlyStrategyFreezeApplicationService.compose(
        semantic_root=semantic_root,
        postgres_dsn=postgres_dsn,
        semantic_namespace_id=namespace,
        runs=OnlyPostgresResearchRunStore(postgres_dsn),
        research_results=results,
        calculation_results=calculation_results,
        datasets=dataset_store,
        specification_resolver=OnlyResearchSpecificationResolver(exact_calculations),
        calculations=exact_calculations,
        audit_time=lambda: NOW + timedelta(seconds=3),
        strategy_composition_verifier=verifier,
        authoring_generations=authoring,
    )
    frozen = freeze.freeze(OnlyStrategyFreezeRequest(completed.run_id, decision_candidate.candidate_fingerprint, "tc1"))
    assert OnlyFrozenStrategyRevisionStore(semantic_root).load_verified(frozen.strategy_fingerprint)
