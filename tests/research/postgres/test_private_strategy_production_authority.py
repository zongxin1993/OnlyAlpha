from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

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
    OnlyCalculationDataType,
    OnlyCalculationEquivalenceEvidenceV2Store,
    OnlyCalculationKind,
    OnlyCalculationRegistry,
    OnlyCalculationTypeReference,
)
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.distribution import OnlyArtifactCalculationImplementation
from onlyalpha.domain.enums import OnlyAdjustmentType, OnlyAggregationSource, OnlyBarAggregation, OnlyPriceType
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBarSpecification, OnlyBarType
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
    ONLY_PRIVATE_FACTOR_API_V1,
    OnlyPrivateAssetExampleImporterV1,
    OnlyPrivateAssetKind,
    OnlyPrivateAssetRevisionBindingResolver,
    OnlyPrivateAssetRevisionReferenceV1,
    OnlyPrivateFactorAsset,
    OnlyPrivateFactorDraft,
    OnlyPrivateFactorExecutableClosureV1,
    OnlyPrivateFactorIsolatedProgramHost,
    OnlyPrivateFactorSnapshotProviderSource,
    OnlyPrivateStrategyAsset,
    OnlyPrivateStrategyDefinitionV1,
    OnlyPrivateStrategyDraft,
    OnlyPrivateStrategyFactorRevisionDependencyV1,
    OnlyPrivateStrategyResearchComposer,
    OnlyPrivateStrategyResearchCompositionError,
    OnlyPrivateStrategyResearchCompositionVerifier,
    OnlyPrivateStrategyResearchContextV1,
    OnlyQuantAssetCatalogGeneration,
    OnlyQuantAssetKind,
    OnlyQuantAssetProvider,
    OnlyQuantAssetProviderManifest,
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
    OnlyResearchAnd,
    OnlyResearchCalculationInput,
    OnlyResearchCalculationInstance,
    OnlyResearchComparison,
    OnlyResearchComparisonOperator,
    OnlyResearchDatasetFieldRef,
    OnlyResearchFixedParameter,
    OnlyResearchSignals,
    OnlyResearchStatisticsRequest,
    OnlyResearchTypedLiteral,
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
from onlyalpha.research.run.generation import OnlyResearchDefinitionRuntimeResolutionV1
from onlyalpha.research.source_cut import OnlySourceClosedCutV1
from onlyalpha.research.specification import OnlyResearchSpecificationResolver
from onlyalpha.runtime.defaults import only_default_engine_services
from onlyalpha.runtime.generation import (
    OnlyCoreExecutionIdentity,
    OnlyRuntimeGenerationManifest,
    OnlyRuntimePrivateFactorBinding,
    OnlyRuntimeProviderBinding,
)
from onlyalpha.runtime.trading.predicate import only_register_trading_predicate_primitives
from onlyalpha.strategy.admission import only_resolve_runtime_strategy_trading
from onlyalpha.strategy.errors import OnlyStrategyFreezeError
from onlyalpha.strategy.freeze import OnlyStrategyFreezeRequest
from onlyalpha.strategy.revision import OnlyStrategyMarketInputContract, OnlyStrategyUniverse
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


def _cardinality_assets(
    assets: OnlyPostgresPrivateAssetStore,
    factor_count: int,
) -> tuple[
    OnlyPrivateAssetRevisionReferenceV1,
    OnlyPrivateStrategyResearchContextV1,
    OnlyQuantAssetCatalogGeneration,
    tuple[OnlyPrivateFactorExecutableClosureV1, ...],
]:
    base_catalog = only_discover_quant_asset_providers()
    closures: list[OnlyPrivateFactorExecutableClosureV1] = []
    providers: list[OnlyQuantAssetProvider] = []
    calculations: list[OnlyResearchCalculationInstance] = []
    dependencies: list[OnlyPrivateStrategyFactorRevisionDependencyV1] = []
    if factor_count == 0:
        calculations.extend(
            (
                OnlyResearchCalculationInstance(
                    "public_indicator",
                    OnlyCalculationTypeReference(OnlyCalculationKind.INDICATOR, "onlyalpha.indicator.rsi", "1"),
                    {
                        "period": OnlyResearchFixedParameter(2),
                        "price_field": OnlyResearchFixedParameter("CLOSE"),
                    },
                    ("value",),
                    (OnlyResearchCalculationInput("value", "bar.close"),),
                ),
                OnlyResearchCalculationInstance(
                    "public_factor",
                    OnlyCalculationTypeReference(OnlyCalculationKind.FACTOR, "example.factor.momentum", "1"),
                    {},
                    ("factor_value",),
                    (
                        OnlyResearchCalculationInput("return_short", "bar.close"),
                        OnlyResearchCalculationInput("return_long", "bar.open"),
                    ),
                ),
            )
        )
    else:
        for index in range(factor_count):
            suffix = chr(ord("a") + index)
            factor_id = f"private.factor.cardinality_{factor_count}_{suffix}"
            assets.put_factor_asset(OnlyPrivateFactorAsset(factor_id))
            assets.save_factor_draft(
                OnlyPrivateFactorDraft(
                    factor_id=factor_id,
                    semantic_version="1",
                    source_text=(
                        "def calculate(api, inputs, parameters):\n"
                        '    return {"value": api.sub(inputs["close"], inputs["previous_close"])}\n'
                    ),
                    factor_api_version=1,
                    factor_api_contract_fingerprint=ONLY_PRIVATE_FACTOR_API_V1.api_contract_fingerprint,
                    input_contract={"close": {"type": "DECIMAL"}, "previous_close": {"type": "DECIMAL"}},
                    parameter_contract={},
                    output_contract={"value": {"type": "DECIMAL", "semantic_type": "FACTOR_VALUE"}},
                    description="Cardinality certification Factor",
                    economic_rationale="Deterministic certification fixture",
                    category="certification",
                )
            )
            _, revision = assets.publish_factor_revision(factor_id)
            closure = OnlyPrivateFactorExecutableClosureV1.create(
                revision,
                ({"close": Decimal(index + 2), "previous_close": Decimal(1)},),
                {},
                host=OnlyPrivateFactorIsolatedProgramHost(3),
            )
            closures.append(closure)
            providers.append(
                OnlyQuantAssetProvider(
                    OnlyQuantAssetProviderManifest(
                        f"private.factor.cardinality_{factor_count}_{suffix}.provider",
                        revision.revision_fingerprint,
                        OnlyQuantAssetKind.FACTOR,
                        OnlyPrivateFactorSnapshotProviderSource(closure.provider_snapshot.snapshot_fingerprint),
                    ),
                    closure.registrations,
                    closure.provider_snapshot,
                )
            )
            calculations.append(
                OnlyResearchCalculationInstance(
                    f"factor_{suffix}",
                    OnlyCalculationTypeReference(OnlyCalculationKind.FACTOR, factor_id, "1"),
                    {},
                    ("value",),
                    (
                        OnlyResearchCalculationInput("close", "bar.close"),
                        OnlyResearchCalculationInput("previous_close", "bar.open"),
                    ),
                )
            )
            dependencies.append(OnlyPrivateStrategyFactorRevisionDependencyV1(factor_id, revision.revision_fingerprint))

    comparisons = tuple(
        OnlyResearchComparison(
            OnlyResearchComparisonOperator.GT,
            OnlyResearchVariableRef(item.instance_key, item.published_outputs[0]),
            OnlyResearchTypedLiteral(OnlyCalculationDataType.DECIMAL, Decimal("0")),
        )
        for item in calculations
    )
    signal = comparisons[0] if len(comparisons) == 1 else OnlyResearchAnd(comparisons)
    eligibility = OnlyResearchComparison(
        OnlyResearchComparisonOperator.GT,
        OnlyResearchDatasetFieldRef("close"),
        OnlyResearchTypedLiteral(OnlyCalculationDataType.DECIMAL, Decimal("0")),
    )
    definition = OnlyPrivateStrategyDefinitionV1(
        1,
        OnlyStrategyUniverse((OnlyInstrumentId.parse("TEST.XSHG"),)),
        OnlyStrategyMarketInputContract(
            OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
            OnlyAggregationSource.EXTERNAL,
            OnlyAdjustmentType.RAW,
        ),
        tuple(calculations),
        tuple(sorted(dependencies)),
        eligibility,
        OnlyResearchSignals(signal, signal),
    )
    strategy_id = f"private.strategy.cardinality_{factor_count}"
    assets.put_strategy_asset(OnlyPrivateStrategyAsset(strategy_id))
    assets.save_strategy_draft(
        OnlyPrivateStrategyDraft(strategy_id, "1", definition.to_dict(), "Cardinality certification", ())
    )
    _, strategy = assets.publish_strategy_revision(strategy_id)
    target = _simple_momentum_context().targets[0]
    context = OnlyPrivateStrategyResearchContextV1(
        "2026-01-05T01:30:00+00:00",
        "2026-01-05T01:34:01+00:00",
        (target,),
        (
            OnlyResearchStatisticsRequest(
                OnlyResearchVariableRef(calculations[-1].instance_key, calculations[-1].published_outputs[0]),
                "forward_return",
                OnlyResearchStatisticsDefinition(method=OnlyResearchStatisticsMethod.IC),
            ),
        ),
    )
    return (
        OnlyPrivateAssetRevisionReferenceV1(
            OnlyPrivateAssetKind.STRATEGY,
            strategy.strategy_id,
            strategy.revision_fingerprint,
        ),
        context,
        OnlyQuantAssetCatalogGeneration((*base_catalog.providers, *providers)),
        tuple(closures),
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


def _runtime_manifest(generation: OnlyAuthoringExecutionGeneration) -> OnlyRuntimeGenerationManifest:
    return _runtime_manifest_for_catalog(generation.catalog, (generation.private_factor_executable_closure,))


def _runtime_manifest_for_catalog(
    catalog: OnlyQuantAssetCatalogGeneration,
    closures: tuple[OnlyPrivateFactorExecutableClosureV1, ...],
) -> OnlyRuntimeGenerationManifest:
    calculations = only_default_engine_services(
        calculation_catalog_generation=catalog
    ).assembler.components.calculations
    implementations = tuple(
        OnlyArtifactCalculationImplementation(
            registration.type_definition.kind.value,
            registration.type_definition.type_id,
            registration.type_definition.semantic_version,
            registration.backend.value,
            registration.implementation_manifest.implementation_fingerprint,
        )
        for registration in calculations.backend_registrations()
        if registration.implementation_manifest is not None
    )
    return OnlyRuntimeGenerationManifest(
        OnlyCoreExecutionIdentity("onlyalpha-test-runtime", "1", "a" * 64),
        ("b" * 64, "c" * 64),
        ("a" * 64, "d" * 64),
        (OnlyRuntimeProviderBinding("onlyalpha.test.runtime", "1", "e" * 64, "d" * 64),),
        catalog.generation_fingerprint,
        implementations,
        tuple(
            OnlyRuntimePrivateFactorBinding(
                closure.provider_snapshot.snapshot_fingerprint,
                only_canonical_fingerprint({"runtime": closure.source_artifact.source_artifact_fingerprint}),
                closure.provider_snapshot.entries[0],
            )
            for closure in closures
        ),
    )


class _ExactRuntimeGenerationAuthority(OnlyTestRuntimeGenerationAuthority):
    def __init__(self, manifests: tuple[OnlyRuntimeGenerationManifest, ...]) -> None:
        if not manifests:
            raise ValueError("RUNTIME_GENERATION_REQUIRED")
        first = manifests[0]
        super().__init__(first.runtime_generation_fingerprint, first.catalog_generation_fingerprint)
        self._manifests = {item.runtime_generation_fingerprint: item for item in manifests}
        self.available_generations = {
            item.runtime_generation_fingerprint: item.catalog_generation_fingerprint for item in manifests
        }

    def require_runtime_generation(self, runtime_generation_fingerprint: str) -> OnlyRuntimeGenerationManifest:
        try:
            return self._manifests[runtime_generation_fingerprint]
        except KeyError as exc:
            raise ValueError("RUNTIME_GENERATION_NOT_FOUND") from exc


class _ExactRuntimeAdmissionResolver:
    def __init__(
        self,
        runtime_generations: _ExactRuntimeGenerationAuthority,
        calculations_by_generation: dict[str, OnlyCalculationRegistry],
        definition_resolvers: dict[str, OnlyResearchDefinitionResolver],
    ) -> None:
        self._runtime_generations = runtime_generations
        self._calculations = calculations_by_generation
        self._definition_resolvers = definition_resolvers

    def resolve(self, fingerprint: str, specification):  # type: ignore[no-untyped-def]
        calculations = self._calculations.get(fingerprint)
        if calculations is None:
            raise ValueError("RUNTIME_GENERATION_NOT_FOUND")
        resolution = OnlyResearchSpecificationResolver(calculations).resolve(specification)
        return OnlyResearchAdmissionResolutionEvidence.from_resolution(resolution)

    def resolve_definition(self, fingerprint: str, definition):  # type: ignore[no-untyped-def]
        resolver = self._definition_resolvers.get(fingerprint)
        manifest = self._runtime_generations.require_runtime_generation(fingerprint)
        if resolver is None:
            raise ValueError("RUNTIME_GENERATION_NOT_FOUND")
        resolution = resolver.resolve(definition)
        return OnlyResearchDefinitionRuntimeResolutionV1(
            definition.definition_fingerprint,
            resolution.specification,
            resolution.specification_fingerprint,
            OnlyResearchAdmissionResolutionEvidence.from_resolution(resolution.specification_resolution),
            tuple(item.to_dict() for item in manifest.private_factor_bindings),
            resolution.specification_resolution.candidates,
            resolution.specification_resolution.signals,
            resolution.workload.result_plan,
        )

    def resolve_strategy_trading_admission(
        self,
        fingerprint,
        graph,
        signals,
        market_input_contract,
        research_implementation_bindings,
    ):  # type: ignore[no-untyped-def]
        calculations = self._calculations.get(fingerprint)
        if calculations is None:
            raise ValueError("RUNTIME_GENERATION_NOT_FOUND")
        return only_resolve_runtime_strategy_trading(
            runtime_generation_fingerprint=fingerprint,
            calculations=calculations,
            graph=graph,
            signals=signals,
            market_input_contract=market_input_contract,
            research_implementation_bindings=tuple(
                SimpleNamespace(**item) for item in research_implementation_bindings
            ),
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
    runtime_manifest = _runtime_manifest(generation)
    runtime_manifest_two = _runtime_manifest(generation_two)
    runtime_generations = _ExactRuntimeGenerationAuthority((runtime_manifest, runtime_manifest_two))
    preview = OnlyPrivateStrategyResearchComposer(assets, generation.catalog).compose(strategy_reference, context)
    preview_two = OnlyPrivateStrategyResearchComposer(assets, generation_two.catalog).compose(
        strategy_reference, context
    )
    assert preview.research_definition == preview_two.research_definition
    expected_run_id = only_novelty_gated_research_run_id(submission_key)
    runtime_generations.bind_work_exact(expected_run_id.value, runtime_manifest.runtime_generation_fingerprint)

    runtime_resolution = _ExactRuntimeAdmissionResolver(
        runtime_generations,
        {
            runtime_manifest.runtime_generation_fingerprint: exact_calculations,
            runtime_manifest_two.runtime_generation_fingerprint: exact_calculations_two,
        },
        {
            runtime_manifest.runtime_generation_fingerprint: definition_resolver,
            runtime_manifest_two.runtime_generation_fingerprint: definition_resolver_two,
        },
    )
    subject = OnlyExactEvaluationIntentResolverV1(
        runtime_generations=runtime_generations,
        runtime_resolution=runtime_resolution,
        authoring_generations=authoring,
    ).resolve(
        definition_resolver.resolve(preview.research_definition).specification,
        runtime_work_id=expected_run_id.value,
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
        research=command,
        runtime_generations=runtime_generations,
        runtime_definition_resolver=runtime_resolution,
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
                runtime_generation_fingerprint=runtime_manifest.runtime_generation_fingerprint,
            )
        )
    finally:
        kernel.stop()

    composition = compositions.load(outcome.run.strategy_research_composition_fingerprint or "")
    assert composition.catalog_generation_fingerprint == runtime_manifest.catalog_generation_fingerprint
    assert outcome.run.authoring_generation_fingerprint is None
    restarted_compositions = OnlyPostgresPrivateStrategyResearchCompositionStore(postgres_dsn)
    assert restarted_compositions.load(composition.composition_fingerprint) == composition
    assert restarted_compositions.load_context(composition.composition_fingerprint) == context

    execution_store = OnlyPostgresResearchExecutionStore(postgres_dsn)
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
        runtime_executor=OnlyEngineResearchRuntimeExecutor(
            layout.root,
            only_default_engine_services(calculation_catalog_generation=generation.catalog),
        ),
        policy=OnlyResearchExecutionPolicy(max_attempts=1),
        now_utc=lambda: NOW + timedelta(seconds=2),
        runtime_generations=runtime_generations,
        process_generation_fingerprint=runtime_manifest.runtime_generation_fingerprint,
    )
    execution = worker.execute_claim(claim)
    assert execution.run is not None and execution.run.state.value == "COMPLETED"
    completed = OnlyPostgresResearchRunStore(postgres_dsn).load(outcome.run.run_id)
    assert completed.strategy_research_composition_fingerprint == composition.composition_fingerprint
    assert completed.authoring_generation_fingerprint is None
    assert completed.calculation_execution_evidence_fingerprints

    verifier = OnlyPrivateStrategyResearchCompositionVerifier(
        OnlyPrivateStrategyResearchComposer(assets, generation.catalog),
        restarted_compositions,
        execution_evidence=OnlyResearchCalculationExecutionEvidenceStore(layout.research_root),
        runtime_generations=runtime_generations,
        runtime_definition_resolver=runtime_resolution,
    )
    verifier.verify(completed)
    evidence_store = OnlyResearchCalculationExecutionEvidenceStore(layout.research_root)
    assert all(
        evidence_store.load_verified(item).research_implementation_bindings
        and evidence_store.load_verified(item).authoring_generation_fingerprint is None
        for item in completed.calculation_execution_evidence_fingerprints
    )

    submission_key_two = OnlyProductCommandId("00000000-0000-4000-8000-000000000955")
    expected_run_id_two = only_novelty_gated_research_run_id(submission_key_two)
    runtime_generations.activate(
        runtime_manifest_two.runtime_generation_fingerprint,
        catalog_generation_fingerprint=runtime_manifest_two.catalog_generation_fingerprint,
    )
    runtime_generations.bind_work_exact(expected_run_id_two.value, runtime_manifest_two.runtime_generation_fingerprint)
    subject_two = OnlyExactEvaluationIntentResolverV1(
        runtime_generations=runtime_generations,
        runtime_resolution=runtime_resolution,
        authoring_generations=authoring_two,
    ).resolve(
        definition_resolver_two.resolve(preview_two.research_definition).specification,
        runtime_work_id=expected_run_id_two.value,
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
        runtime_generation_fingerprint=runtime_manifest_two.runtime_generation_fingerprint,
        strategy_research_composition_fingerprint=composition.composition_fingerprint,
    )
    execution_store_two = OnlyPostgresResearchExecutionStore(postgres_dsn)
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
        runtime_executor=OnlyEngineResearchRuntimeExecutor(
            layout.root,
            only_default_engine_services(calculation_catalog_generation=generation_two.catalog),
        ),
        policy=OnlyResearchExecutionPolicy(max_attempts=1),
        now_utc=lambda: NOW + timedelta(seconds=5),
        runtime_generations=runtime_generations,
        process_generation_fingerprint=runtime_manifest_two.runtime_generation_fingerprint,
    ).execute_claim(claim_two)
    assert execution_two.run is not None and execution_two.run.state.value == "COMPLETED"
    completed_two = OnlyPostgresResearchRunStore(postgres_dsn).load(drifted.run.run_id)
    assert completed_two.authoring_generation_fingerprint is None
    assert completed_two.calculation_execution_evidence_fingerprints
    with pytest.raises(
        OnlyPrivateStrategyResearchCompositionError, match="Composition Catalog differs from Runtime Catalog"
    ):
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
    exact_resolution = runtime_resolution.resolve_definition(
        runtime_manifest.runtime_generation_fingerprint,
        preview.research_definition,
    )
    only_register_trading_predicate_primitives(exact_calculations)
    decision_candidate = next(item for item in exact_resolution.candidates if item.calculation_id == "decision")
    certification = OnlyCalculationEquivalenceCertificationApplicationService(
        exact_calculations,
        OnlyCalculationEquivalenceEvidenceV2Store(semantic_root),
    )
    for node in decision_candidate.graph.nodes:
        certification.certify(node)
    ambient_calculations = only_default_engine_services().assembler.components.calculations
    only_register_trading_predicate_primitives(ambient_calculations)
    freeze = OnlyStrategyFreezeApplicationService.compose(
        semantic_root=semantic_root,
        postgres_dsn=postgres_dsn,
        semantic_namespace_id=namespace,
        runs=OnlyPostgresResearchRunStore(postgres_dsn),
        research_results=results,
        calculation_results=calculation_results,
        datasets=dataset_store,
        specification_resolver=OnlyResearchSpecificationResolver(exact_calculations),
        calculations=ambient_calculations,
        audit_time=lambda: NOW + timedelta(seconds=3),
        strategy_composition_verifier=verifier,
        runtime_trading_resolver=runtime_resolution,
    )
    frozen = freeze.freeze(OnlyStrategyFreezeRequest(completed.run_id, decision_candidate.candidate_fingerprint, "tc1"))
    assert OnlyFrozenStrategyRevisionStore(semantic_root).load_verified(frozen.strategy_fingerprint)

    class _WrongRuntimeTradingResolver:
        def resolve_strategy_trading_admission(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            return replace(
                runtime_resolution.resolve_strategy_trading_admission(*args, **kwargs),
                runtime_generation_fingerprint="f" * 64,
            )

    mismatched_freeze = OnlyStrategyFreezeApplicationService.compose(
        semantic_root=semantic_root,
        postgres_dsn=postgres_dsn,
        semantic_namespace_id=namespace,
        runs=OnlyPostgresResearchRunStore(postgres_dsn),
        research_results=results,
        calculation_results=calculation_results,
        datasets=dataset_store,
        specification_resolver=OnlyResearchSpecificationResolver(exact_calculations),
        calculations=ambient_calculations,
        audit_time=lambda: NOW + timedelta(seconds=4),
        strategy_composition_verifier=verifier,
        runtime_trading_resolver=_WrongRuntimeTradingResolver(),
    )
    with pytest.raises(OnlyStrategyFreezeError, match="IMPLEMENTATION_IDENTITY_MISMATCH"):
        mismatched_freeze.freeze(
            OnlyStrategyFreezeRequest(completed.run_id, decision_candidate.candidate_fingerprint, "tc1-mismatch")
        )


@pytest.mark.parametrize("factor_count", (0, 2))
def test_private_strategy_cardinality_production_chain(
    postgres_dsn: str,
    tmp_path: Path,
    factor_count: int,
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    assets = OnlyPostgresPrivateAssetStore(postgres_dsn)
    strategy_reference, context, catalog, closures = _cardinality_assets(assets, factor_count)
    layout = OnlyUserDataLayout(tmp_path / f"user-data-{factor_count}")
    semantic_root = layout.research_root
    namespace = OnlyResearchSemanticStoreIdentity(semantic_root).initialize()
    dataset_store = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    dataset, partitions = _test_xshg_snapshot()
    dataset_store.commit(dataset, partitions)
    calculations = only_default_engine_services(
        calculation_catalog_generation=catalog
    ).assembler.components.calculations
    definition_resolver = OnlyResearchDefinitionResolver(
        calculations,
        _Datasets(dataset_store, dataset.snapshot_fingerprint),
    )
    runtime_manifest = _runtime_manifest_for_catalog(catalog, closures)
    assert len(runtime_manifest.private_factor_bindings) == factor_count
    runtime_generations = _ExactRuntimeGenerationAuthority((runtime_manifest,))
    runtime_resolution = _ExactRuntimeAdmissionResolver(
        runtime_generations,
        {runtime_manifest.runtime_generation_fingerprint: calculations},
        {runtime_manifest.runtime_generation_fingerprint: definition_resolver},
    )
    preview = OnlyPrivateStrategyResearchComposer(assets, catalog).compose(strategy_reference, context)
    submission_key = OnlyProductCommandId(f"00000000-0000-4000-8000-00000000096{factor_count}")
    expected_run_id = only_novelty_gated_research_run_id(submission_key)
    runtime_generations.bind_work_exact(expected_run_id.value, runtime_manifest.runtime_generation_fingerprint)
    subject = OnlyExactEvaluationIntentResolverV1(
        runtime_generations=runtime_generations,
        runtime_resolution=runtime_resolution,
    ).resolve(
        definition_resolver.resolve(preview.research_definition).specification,
        runtime_work_id=expected_run_id.value,
    )
    memory_revisions = OnlyExperimentMemoryRevisionStore(layout.experiment_memory_projection_root)
    initial_memory = OnlyExperimentMemoryProjectionV1(_memory_manifest(), ())
    memory_revisions._publish_and_activate(initial_memory)
    novelty_policies = OnlyNoveltyPolicyStore(layout.research_root)
    novelty_policies.put(policy())
    novelty_decisions = OnlyNoveltyDecisionAuthority(layout.research_root)
    novelty_decisions.seal_from_request(
        OnlyNoveltyDecisionRequestV2(submission_key, "default-novelty", "1", subject),
        initial_memory.revision_fingerprint,
        memory_revisions,
        novelty_policies,
    )
    run_store = OnlyPostgresResearchRunStore(postgres_dsn)
    product_commands = OnlyPostgresProductCommandAuthority(postgres_dsn)
    command = OnlyResearchCommandService(
        admission=OnlyResearchRunAdmissionService(
            resolver=OnlyResearchSpecificationResolver(calculations),
            dataset_store=dataset_store,
            now_utc=lambda: NOW,
        ),
        store=run_store,
        now_utc=lambda: NOW,
        runtime_generations=runtime_generations,
        command_admissions=product_commands,
        runtime_generation_resolver=runtime_resolution,
        novelty_decisions=novelty_decisions,
        memory_builder=_MemoryBuilder(memory_revisions),
        memory_revisions=memory_revisions,
    )
    compositions = OnlyPostgresPrivateStrategyResearchCompositionStore(postgres_dsn)
    strategy_research = OnlyPrivateStrategyResearchApplicationService(
        composer=OnlyPrivateStrategyResearchComposer(assets, catalog),
        compositions=compositions,
        research=command,
        runtime_generations=runtime_generations,
        runtime_definition_resolver=runtime_resolution,
    )
    kernel = OnlyAlphaKernelHost()
    kernel.start()
    try:
        outcome = only_compose_research_product_boundary(
            admission=kernel,
            commands=command,
            queries=OnlyResearchRunQueryService(run_store),
            strategy_research=strategy_research,
        ).submit_private_strategy_research(
            OnlySubmitPrivateStrategyResearch(
                submission_key=submission_key,
                strategy_revision=strategy_reference,
                research_context=context,
                runtime_generation_fingerprint=runtime_manifest.runtime_generation_fingerprint,
            )
        )
    finally:
        kernel.stop()

    composition = OnlyPostgresPrivateStrategyResearchCompositionStore(postgres_dsn).load(
        outcome.run.strategy_research_composition_fingerprint or ""
    )
    assert composition.catalog_generation_fingerprint == runtime_manifest.catalog_generation_fingerprint
    execution_store = OnlyPostgresResearchExecutionStore(postgres_dsn)
    claim = execution_store.claim_next(
        worker_instance_id=OnlyResearchWorkerInstanceId(f"00000000-0000-4000-8000-00000000097{factor_count}"),
        attempt_id=OnlyResearchRunAttemptId(f"00000000-0000-4000-8000-00000000098{factor_count}"),
        lease_duration=timedelta(minutes=2),
        max_attempts=1,
        run_started_at=NOW + timedelta(seconds=1),
        eligible_run_ids=(outcome.run.run_id.value,),
    )
    assert claim is not None
    execution = OnlyResearchWorker(
        worker_instance_id=claim.attempt.worker_instance_id,
        execution_store=execution_store,
        run_store=OnlyPostgresResearchRunStore(postgres_dsn),
        resolver=OnlyResearchSpecificationResolver(calculations),
        dataset_store=dataset_store,
        runtime_executor=OnlyEngineResearchRuntimeExecutor(
            layout.root,
            only_default_engine_services(calculation_catalog_generation=catalog),
        ),
        policy=OnlyResearchExecutionPolicy(max_attempts=1),
        now_utc=lambda: NOW + timedelta(seconds=2),
        runtime_generations=runtime_generations,
        process_generation_fingerprint=runtime_manifest.runtime_generation_fingerprint,
    ).execute_claim(claim)
    assert execution.run is not None and execution.run.state.value == "COMPLETED"
    completed = OnlyPostgresResearchRunStore(postgres_dsn).load(outcome.run.run_id)
    verifier = OnlyPrivateStrategyResearchCompositionVerifier(
        OnlyPrivateStrategyResearchComposer(assets, catalog),
        OnlyPostgresPrivateStrategyResearchCompositionStore(postgres_dsn),
        execution_evidence=OnlyResearchCalculationExecutionEvidenceStore(layout.research_root),
        runtime_generations=runtime_generations,
        runtime_definition_resolver=runtime_resolution,
    )
    verifier.verify(completed)
    OnlyPostgresResearchDeploymentStore(postgres_dsn).initialize(namespace)
    calculation_results = OnlyParquetResearchCalculationResultStore(
        layout.research_calculation_result_root,
        dataset_store,
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
    exact_resolution = runtime_resolution.resolve_definition(
        runtime_manifest.runtime_generation_fingerprint,
        preview.research_definition,
    )
    only_register_trading_predicate_primitives(calculations)
    decision_candidate = next(item for item in exact_resolution.candidates if item.calculation_id == "decision")
    certification = OnlyCalculationEquivalenceCertificationApplicationService(
        calculations,
        OnlyCalculationEquivalenceEvidenceV2Store(semantic_root),
    )
    for node in decision_candidate.graph.nodes:
        certification.certify(node)
    ambient_calculations = only_default_engine_services().assembler.components.calculations
    only_register_trading_predicate_primitives(ambient_calculations)
    frozen = OnlyStrategyFreezeApplicationService.compose(
        semantic_root=semantic_root,
        postgres_dsn=postgres_dsn,
        semantic_namespace_id=namespace,
        runs=OnlyPostgresResearchRunStore(postgres_dsn),
        research_results=results,
        calculation_results=calculation_results,
        datasets=dataset_store,
        specification_resolver=OnlyResearchSpecificationResolver(calculations),
        calculations=ambient_calculations,
        audit_time=lambda: NOW + timedelta(seconds=3),
        strategy_composition_verifier=verifier,
        runtime_trading_resolver=runtime_resolution,
    ).freeze(OnlyStrategyFreezeRequest(completed.run_id, decision_candidate.candidate_fingerprint, "tc2r-cardinality"))
    revision = OnlyFrozenStrategyRevisionStore(semantic_root).load_verified(frozen.strategy_fingerprint)
    private_entries = tuple(item.entry for item in runtime_manifest.private_factor_bindings)
    for entry in private_entries:
        assert any(
            binding.research_implementation_fingerprint == entry.research_implementation_fingerprint
            and binding.trading_implementation_fingerprint == entry.trading_implementation_fingerprint
            for binding in revision.implementation_bindings
        )
    assert OnlyPostgresPrivateAssetStore(postgres_dsn).load_strategy_revision(
        strategy_reference.private_asset_id,
        strategy_reference.private_asset_revision_fingerprint,
    )
