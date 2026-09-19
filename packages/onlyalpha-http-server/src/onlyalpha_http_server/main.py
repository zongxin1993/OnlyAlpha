"""Explicit full Research API composition root."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import uvicorn
from onlyalpha_authoring_execution_worker.generation import (
    OnlyAuthoringExecutionGenerationStore,
    OnlyVerifiedAuthoringGenerationReader,
)
from onlyalpha_runtime_generation_manager import (
    OnlyHistoricalGenerationHostManager,
    OnlyLocalImmutableArtifactStore,
    OnlyRuntimeGenerationBuilder,
    OnlyRuntimeGenerationRegistry,
)
from onlyalpha_runtime_generation_manager.catalog_context import (
    OnlyRuntimeGenerationExactCatalogDescriptorReader,
)

from onlyalpha.application.catalog_context import OnlyExactCatalogContextQueryService
from onlyalpha.application.private_strategy_research import OnlyPrivateStrategyResearchApplicationService
from onlyalpha.application.product_boundary import only_compose_research_product_boundary
from onlyalpha.application.qualification_product import (
    OnlyQualificationProductService,
    OnlyQualificationQueryService,
)
from onlyalpha.application.research_advisory import OnlyResearchNearDuplicateQueryService
from onlyalpha.application.search_product import (
    OnlySearchProductCommandServiceV1,
    OnlySearchProductQueryServiceV1,
)
from onlyalpha.application.strategy_authority import (
    OnlyStrategyFreezeApplicationService,
    OnlyStrategyFreezeProjectionReconciliationApplicationService,
)
from onlyalpha.application.strategy_product import (
    OnlyStrategyFreezeProductService,
    OnlyStrategyPromotionProductService,
    OnlyStrategyQueryService,
)
from onlyalpha.backtest import (
    OnlyBacktestAdmissionService,
    OnlyBacktestCommandService,
    OnlyBacktestDeploymentCatalog,
    OnlyBacktestEvidenceStore,
    OnlyBacktestMarketProductResourceRegistry,
    OnlyBacktestQueryService,
    OnlyMarketProductBacktestAdmissionAdapter,
    only_default_backtest_profile_registry,
    only_load_backtest_deployment_catalog,
    only_load_backtest_market_product_resources,
)
from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.core.clock import only_system_utc_now
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.fee.broker_contract import OnlyBrokerFeeContractRegistry
from onlyalpha.kernel import OnlyAlphaKernelHost, OnlyKernelHostError, OnlyKernelLifecycleStep, OnlyKernelState
from onlyalpha.market.product import OnlyMarketProductFactoryRegistry, OnlyMarketProductResolutionContext
from onlyalpha.output.user_data import OnlyUserDataLayout
from onlyalpha.persistence.postgres import (
    OnlyPostgresConfig,
    OnlyPostgresKernelAuthorityGuard,
    OnlyPostgresOperationalConnectionOptions,
    OnlyPostgresProductCommandAuthority,
    OnlyPostgresResearchDeploymentStore,
    OnlyPostgresResearchRunStore,
    OnlyPostgresSchemaVerifier,
    only_assert_supported_postgres_server,
)
from onlyalpha.persistence.postgres.backtest_store import OnlyPostgresBacktestStore
from onlyalpha.persistence.postgres.private_asset_store import OnlyPostgresPrivateAssetStore
from onlyalpha.persistence.postgres.private_strategy_research_composition_store import (
    OnlyPostgresPrivateStrategyResearchCompositionStore,
)
from onlyalpha.persistence.postgres.research_source_cut_store import OnlyPostgresResearchSourceCutAuthority
from onlyalpha.persistence.postgres.strategy_product_store import OnlyPostgresStrategyProductStore
from onlyalpha.quant_assets import OnlyQuantAssetCatalogGeneration
from onlyalpha.quant_assets.private import OnlyPrivateAssetRevisionBindingResolver
from onlyalpha.quant_assets.private_strategy_composition import (
    OnlyPrivateStrategyResearchComposer,
    OnlyPrivateStrategyResearchCompositionVerifier,
)
from onlyalpha.research.agent.source_cut import OnlyAgentProvenanceClosedCutAuthority
from onlyalpha.research.artifact.reader import OnlyResearchArtifactProfileReader
from onlyalpha.research.calculation.execution_evidence import OnlyResearchCalculationExecutionEvidenceStore
from onlyalpha.research.calculation.result_store import OnlyParquetResearchCalculationResultStore
from onlyalpha.research.command.query import OnlyResearchRunQueryService
from onlyalpha.research.command.service import OnlyResearchCommandService
from onlyalpha.research.dataset import OnlyDatasetEconomicBindingStore, OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.definition.resolver import OnlyResearchDefinitionResolver
from onlyalpha.research.evaluation.factor_pair.result_store import (
    OnlyParquetResearchFactorPairStatisticsResultStore,
)
from onlyalpha.research.evaluation.result_store import OnlyParquetResearchStatisticsResultStore
from onlyalpha.research.evaluation.subject import OnlyExactEvaluationIntentResolverV1
from onlyalpha.research.evaluation.summary.execution import OnlyResearchEffectSummaryExecutor
from onlyalpha.research.evaluation.summary.reader import OnlyResearchStatisticsResultReader
from onlyalpha.research.evaluation.summary.result_store import OnlyJsonResearchSummaryStatisticsResultStore
from onlyalpha.research.experiment import (
    OnlyJsonSearchProvenanceStore,
    OnlySearchExperimentManifestV2,
    OnlySearchExperimentManifestV3,
)
from onlyalpha.research.memory.advisory import (
    OnlyExperimentMemoryAdvisoryProjectionBuilder,
    OnlyNearDuplicateThresholdPolicyV1,
)
from onlyalpha.research.memory.production import (
    OnlyCapturableMemoryCutReader,
    OnlyExperimentMemoryProductionBuilder,
    OnlyExperimentMemoryReferenceReadersV1,
)
from onlyalpha.research.memory.store import OnlyExperimentMemoryRevisionStore
from onlyalpha.research.novelty.decision_store import OnlyNoveltyDecisionAuthority
from onlyalpha.research.operations.deployment import (
    OnlyResearchDeploymentCoherenceVerifier,
    OnlyResearchFrozenDeploymentCheck,
    OnlyResearchSemanticStoreIdentity,
)
from onlyalpha.research.operations.readiness import (
    OnlyResearchReadiness,
    OnlyResearchReadinessStatus,
    OnlyResearchRequiredRoot,
    OnlyResearchServiceReadinessProbe,
)
from onlyalpha.research.result.assembler import OnlyResearchResultAssembler
from onlyalpha.research.result.result_store import OnlyJsonResearchResultStore
from onlyalpha.research.run.admission import OnlyResearchRunAdmissionService
from onlyalpha.research.run.generation import OnlyResearchHostedRuntimeGenerationResolver
from onlyalpha.research.search.parameter.context import OnlyParameterSearchContextResolver
from onlyalpha.research.search.parameter.errors import OnlyParameterSearchStoreError
from onlyalpha.research.search.parameter.evidence import OnlyParameterResearchEvidenceReader
from onlyalpha.research.search.parameter.execution import OnlyHostedParameterGenerationExecutionV1
from onlyalpha.research.search.parameter.integration import (
    OnlyParameterResearchCommandGatewayV1,
    OnlyParameterResearchEvidenceFinalizerV1,
)
from onlyalpha.research.search.parameter.product import OnlyParameterSearchProductAdapterV1
from onlyalpha.research.search.parameter.store import OnlyJsonParameterSearchStore
from onlyalpha.research.search.symbolic.context import OnlySymbolicSearchContextResolver
from onlyalpha.research.search.symbolic.errors import OnlySymbolicSearchStoreError
from onlyalpha.research.search.symbolic.execution import OnlyHostedSymbolicGenerationExecutionV1
from onlyalpha.research.search.symbolic.product import (
    OnlySymbolicResearchCommandGatewayV1,
    OnlySymbolicSearchProductAdapterV1,
)
from onlyalpha.research.search.symbolic.store import OnlyJsonSymbolicSearchStore
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver
from onlyalpha.strategy.qualification import OnlyQualificationEvaluator, OnlyQualificationPolicyRevision
from onlyalpha.strategy.qualification_store import (
    OnlyQualificationDecisionStore,
    OnlyQualificationPolicyStore,
    _only_compose_qualification_decision_authority,
)
from onlyalpha.strategy.store import OnlyFrozenStrategyRevisionStore

from .agent_gateway import OnlyAgentNodeGatewayConfigV1, OnlyAgentNodeHttpGatewayV1
from .app import create_product_app
from .composition import only_configure_product_registries
from .health import OnlyKernelResearchReadinessProjection
from .research.search_authoring_routes import OnlySearchAuthoringValue
from .search import OnlySearchProductHttpServiceV1


class _ResearchProductVerification:
    def __init__(self, probe: OnlyResearchServiceReadinessProbe) -> None:
        self._probe = probe
        self._evidence: OnlyResearchReadiness | None = None

    @property
    def evidence(self) -> OnlyResearchReadiness | None:
        return self._evidence

    def verify(self) -> None:
        evidence = self._probe.inspect()
        self._evidence = evidence
        if evidence.status is not OnlyResearchReadinessStatus.READY:
            raise RuntimeError(evidence.reason or "RESEARCH_SERVICE_NOT_READY")


class _UnavailableProductAuthority:
    """Fail-closed placeholder used only while the Product Kernel is unavailable."""

    def __getattr__(self, name: str) -> object:
        raise RuntimeError(f"PRODUCT_KERNEL_NOT_READY: {name}")


class _SearchAuthoringInputReader:
    """Exact dispatch over existing Search-owned immutable stores."""

    def __init__(
        self,
        symbolic: OnlyJsonSymbolicSearchStore,
        parameter: OnlyJsonParameterSearchStore,
    ) -> None:
        self._symbolic = symbolic
        self._parameter = parameter

    def load_search_authoring_input_verified(self, reference_kind: str, fingerprint: str) -> OnlySearchAuthoringValue:
        if reference_kind == "SYMBOLIC_SEARCH_SPACE":
            return self._symbolic.load_search_space_intrinsic_verified(fingerprint)
        if reference_kind == "RESEARCH_EVALUATION":
            return self._symbolic.load_evaluation_contract_intrinsic_verified(fingerprint)
        if reference_kind == "PARAMETER_SEARCH_SPACE":
            return self._parameter.load_search_space_intrinsic_verified(fingerprint)
        if reference_kind == "SEARCH_POLICY":
            return self._parameter.load_policy_intrinsic_verified(fingerprint)
        if reference_kind == "SEARCH_ALGORITHM":
            values: list[OnlySearchAuthoringValue] = []
            try:
                values.append(self._symbolic.load_algorithm_implementation_manifest_intrinsic_verified(fingerprint))
            except OnlySymbolicSearchStoreError as error:
                if error.code != "SEARCH_ALGORITHM_MANIFEST_NOT_FOUND":
                    raise
            try:
                values.append(self._parameter.load_algorithm_manifest_intrinsic_verified(fingerprint))
            except OnlyParameterSearchStoreError as error:
                if error.code != "PARAMETER_ALGORITHM_MANIFEST_NOT_FOUND":
                    raise
            if len(values) != 1:
                raise LookupError("SEARCH_ALGORITHM_NOT_FOUND_OR_AMBIGUOUS")
            return values[0]
        raise LookupError(reference_kind)


class _GenerationOwnedCatalogReader:
    """Fail closed if a historical Search path attempts parent-runtime Catalog execution."""

    def generation(self, fingerprint: str) -> object:
        raise RuntimeError(f"SEARCH_CATALOG_IS_RUNTIME_GENERATION_OWNED:{fingerprint}")


class _SearchContextReader:
    """Dispatch shared provenance verification by the Experiment's exact schema."""

    def __init__(
        self,
        symbolic: OnlySymbolicSearchContextResolver,
        parameter: OnlyParameterSearchContextResolver,
    ) -> None:
        self._symbolic = symbolic
        self._parameter = parameter

    def _resolver(
        self, experiment: OnlySearchExperimentManifestV2 | OnlySearchExperimentManifestV3
    ) -> OnlySymbolicSearchContextResolver | OnlyParameterSearchContextResolver:
        if isinstance(experiment, OnlySearchExperimentManifestV2):
            return self._symbolic
        if isinstance(experiment, OnlySearchExperimentManifestV3):
            return self._parameter
        raise TypeError("SEARCH_EXPERIMENT_SCHEMA_UNSUPPORTED")

    def __getattr__(self, name: str) -> object:
        if name.startswith("_"):
            raise AttributeError(name)

        def dispatch(
            experiment: OnlySearchExperimentManifestV2 | OnlySearchExperimentManifestV3,
            *args: object,
        ) -> object:
            method = getattr(self._resolver(experiment), name)
            return method(experiment, *args)

        return dispatch


class _SearchTerminalProjectionReader:
    def __init__(self, symbolic: OnlyJsonSymbolicSearchStore, parameter: OnlyJsonParameterSearchStore) -> None:
        self._symbolic = symbolic
        self._parameter = parameter

    def load_terminal_projection_verified(self, fingerprint: str) -> object:
        try:
            return self._symbolic.load_enumeration_result_by_fingerprint_verified(fingerprint)
        except OnlySymbolicSearchStoreError as error:
            if not error.code.endswith("_NOT_FOUND"):
                raise
        return self._parameter.load_feedback_decision_intrinsic_verified(fingerprint)


def _compose_search_product(
    *,
    layout: OnlyUserDataLayout,
    calculations: OnlyCalculationRegistry,
    datasets: OnlyParquetResearchDatasetSnapshotStore,
    research_commands: OnlyResearchCommandService,
    research_runs: OnlyResearchRunQueryService,
    research_results: OnlyJsonResearchResultStore,
    statistics_results: OnlyResearchStatisticsResultReader,
    calculation_results: OnlyParquetResearchCalculationResultStore,
    legacy_statistics_results: OnlyParquetResearchStatisticsResultStore,
    summary_statistics_results: OnlyJsonResearchSummaryStatisticsResultStore,
    product_commands: OnlyPostgresProductCommandAuthority,
    runtime_generations: OnlyRuntimeGenerationRegistry,
    generation_host: OnlyHistoricalGenerationHostManager,
    symbolic: OnlyJsonSymbolicSearchStore,
    parameter: OnlyJsonParameterSearchStore,
    symbolic_contexts: OnlySymbolicSearchContextResolver,
    parameter_contexts: OnlyParameterSearchContextResolver,
    provenance: OnlyJsonSearchProvenanceStore,
) -> tuple[
    OnlySearchProductCommandServiceV1,
    OnlySearchProductQueryServiceV1,
    OnlyJsonSearchProvenanceStore,
]:
    symbolic_adapter = OnlySymbolicSearchProductAdapterV1(
        symbolic_store=symbolic,
        provenance=provenance,
        contexts=symbolic_contexts,
        resolver=OnlyResearchSpecificationResolver(calculations),
        research_commands=OnlySymbolicResearchCommandGatewayV1(cast(Any, research_commands), research_results),
        generation_execution=OnlyHostedSymbolicGenerationExecutionV1(generation_host, layout.research_dataset_root),
        product_receipts=product_commands,
        research_runs=research_runs,
    )
    parameter_adapter = OnlyParameterSearchProductAdapterV1(
        parameter_store=parameter,
        evaluation_store=symbolic,
        provenance=provenance,
        contexts=parameter_contexts,
        calculation_registry=calculations,
        evidence_reader=OnlyParameterResearchEvidenceReader(
            iteration_results=provenance,
            iteration_plans=provenance,
            research_results=research_results,
            statistics_results=statistics_results,
        ),
        resolver=OnlyResearchSpecificationResolver(calculations),
        research_commands=OnlyParameterResearchCommandGatewayV1(
            cast(Any, research_commands),
            OnlyParameterResearchEvidenceFinalizerV1(
                research_results=cast(Any, research_results),
                summary_executor=OnlyResearchEffectSummaryExecutor(
                    legacy_statistics_results,
                    summary_statistics_results,
                ),
                result_assembler=OnlyResearchResultAssembler(
                    statistics_results,
                    audit_time=only_system_utc_now,
                    calculation_result_store=calculation_results,
                ),
            ),
        ),
        generation_execution=OnlyHostedParameterGenerationExecutionV1(generation_host, layout.research_dataset_root),
        product_receipts=product_commands,
        research_runs=research_runs,
    )
    adapters = (symbolic_adapter, parameter_adapter)
    return (
        OnlySearchProductCommandServiceV1(
            command_admissions=product_commands,
            command_receipts=product_commands,
            runtime_generations=runtime_generations,
            adapters=adapters,
            now_utc=only_system_utc_now,
        ),
        OnlySearchProductQueryServiceV1(adapters),
        provenance,
    )


def _compose_experiment_memory_projection_builder(
    *,
    layout: OnlyUserDataLayout,
    postgres_dsn: str,
    search: OnlyJsonSearchProvenanceStore,
    results: OnlyJsonResearchResultStore,
    statistics: OnlyParquetResearchStatisticsResultStore,
    factor_pair_statistics: OnlyParquetResearchFactorPairStatisticsResultStore,
    summary_statistics: OnlyJsonResearchSummaryStatisticsResultStore,
    qualification_decisions: OnlyQualificationDecisionStore,
    datasets: OnlyParquetResearchDatasetSnapshotStore,
    catalogs: OnlyRuntimeGenerationExactCatalogDescriptorReader,
    calculations: OnlyParquetResearchCalculationResultStore,
    runtime_generations: OnlyRuntimeGenerationRegistry,
    authoring_generations: OnlyVerifiedAuthoringGenerationReader,
) -> tuple[OnlyExperimentMemoryProductionBuilder, OnlyExperimentMemoryAdvisoryProjectionBuilder]:
    """The Product root fixes all eleven owners; no external reference callback enters."""
    postgres = OnlyPostgresResearchSourceCutAuthority(postgres_dsn)
    sources: dict[str, OnlyCapturableMemoryCutReader] = {
        "SEARCH_PROVENANCE": search,
        "AGENT_PROVENANCE": OnlyAgentProvenanceClosedCutAuthority(layout.research_root),
        "RESEARCH_RESULT": results,
        "RESEARCH_STATISTICS": statistics,
        "RESEARCH_FACTOR_PAIR_STATISTICS": factor_pair_statistics,
        "RESEARCH_SUMMARY_STATISTICS": summary_statistics,
        "QUALIFICATION_DECISION": qualification_decisions,
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
        OnlyJsonSymbolicSearchStore(layout.research_root),
        OnlyJsonParameterSearchStore(layout.research_root),
        calculations,
        runtime_generations,
        authoring_generations,
        OnlyQualificationPolicyStore(layout.research_root),
        OnlyBacktestEvidenceStore(layout.root),
    )
    revisions = OnlyExperimentMemoryRevisionStore(layout.experiment_memory_projection_root)
    return (
        OnlyExperimentMemoryProductionBuilder(sources, references, revisions),
        OnlyExperimentMemoryAdvisoryProjectionBuilder(revisions, sources, references, cast(Any, calculations)),
    )


def _verify_postgres_server(operational_dsn: str) -> None:
    only_assert_supported_postgres_server(operational_dsn)


def _verify_calculation_registry(calculations: OnlyCalculationRegistry) -> None:
    calculations.type_definitions()


def _verify_product_registries(
    calculations: OnlyCalculationRegistry,
    market_products: OnlyMarketProductFactoryRegistry,
    catalog: OnlyBacktestDeploymentCatalog,
    resources: OnlyBacktestMarketProductResourceRegistry,
) -> None:
    _verify_calculation_registry(calculations)
    for fingerprint in catalog.configuration_fingerprints:
        configuration = catalog.configurations.resolve(fingerprint)
        market_products.resolve(
            configuration.config,
            OnlyMarketProductResolutionContext(resources, catalog.document(fingerprint).instruments),
        )


def _reconcile_strategy_projections(layout: OnlyUserDataLayout, postgres_dsn: str) -> None:
    semantic_namespace_id = OnlyResearchSemanticStoreIdentity(layout.research_root).load_verified()
    OnlyStrategyFreezeProjectionReconciliationApplicationService.compose(
        semantic_root=layout.research_root,
        postgres_dsn=postgres_dsn,
        semantic_namespace_id=semantic_namespace_id,
        audit_time=only_system_utc_now,
    ).reconcile_all()


def _load_qualification_policies(paths: tuple[Path, ...], store: OnlyQualificationPolicyStore) -> None:
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError(f"Qualification Policy must be an object: {path}")
        store.put(OnlyQualificationPolicyRevision.from_dict(payload))


def _compose_backtest_product(
    postgres_dsn: str,
    operational_options: OnlyPostgresOperationalConnectionOptions,
    layout: OnlyUserDataLayout,
    market_products: OnlyMarketProductFactoryRegistry,
    catalog: OnlyBacktestDeploymentCatalog,
    resources: OnlyBacktestMarketProductResourceRegistry,
    runtime_generations: OnlyRuntimeGenerationRegistry,
) -> tuple[OnlyBacktestCommandService, OnlyBacktestQueryService, OnlyPostgresBacktestStore]:
    semantic_namespace_id = OnlyResearchSemanticStoreIdentity(layout.research_root).load_verified()
    strategies = OnlyFrozenStrategyRevisionStore(layout.research_root)
    promotions = OnlyPostgresStrategyProductStore(postgres_dsn, semantic_namespace_id, operational_options)
    datasets = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    store = OnlyPostgresBacktestStore(postgres_dsn, operational_options)
    evidence = OnlyBacktestEvidenceStore(layout.root)
    strategy_queries = OnlyStrategyQueryService(strategies, promotions)
    admission = OnlyBacktestAdmissionService(
        strategies=strategies,
        promotions=strategy_queries,
        dataset_bindings=OnlyDatasetEconomicBindingStore(layout.root),
        datasets=datasets,
        market_products=OnlyMarketProductBacktestAdmissionAdapter(
            factories=market_products,
            configurations=catalog.configurations,
            resources=resources,
            instruments=catalog,
        ),
        profiles=only_default_backtest_profile_registry(),
        kernel_semantics_version="ONLYALPHA_KERNEL_SEMANTICS@1",
    )
    return (
        OnlyBacktestCommandService(
            admission=admission,
            store=store,
            now_utc=only_system_utc_now,
            runtime_generations=runtime_generations,
        ),
        OnlyBacktestQueryService(store, evidence),
        store,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="onlyalpha-http-server")
    parser.add_argument("--user-data-root", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--backtest-product-config",
        action="append",
        type=Path,
        default=[],
        help="verified operator-owned Product configuration document; repeat for each Market Product",
    )
    parser.add_argument("--runtime-generation-authority-root", type=Path)
    parser.add_argument("--authoring-generation-root", type=Path)
    parser.add_argument("--agent-node-url")
    parser.add_argument("--agent-control-token-file", type=Path)
    parser.add_argument(
        "--qualification-policy",
        action="append",
        type=Path,
        default=[],
        help="operator-owned exact Qualification Policy Revision manifest; repeat as required",
    )
    parser.add_argument(
        "--backtest-market-resource",
        action="append",
        type=Path,
        default=[],
        help="verified plugin-owned Market Product resource document; repeat as required",
    )
    args = parser.parse_args(argv)
    if (args.agent_node_url is None) != (args.agent_control_token_file is None):
        raise ValueError("AGENT_GATEWAY_CONFIG_INCOMPLETE")
    postgres = OnlyPostgresConfig.from_environment()
    operational_options = OnlyPostgresOperationalConnectionOptions()
    operational_dsn = postgres.operational_dsn(operational_options)
    schema = OnlyPostgresSchemaVerifier(operational_dsn)
    layout = OnlyUserDataLayout(args.user_data_root)
    qualification_policies = OnlyQualificationPolicyStore(layout.research_root)
    qualification_decisions, qualification_decision_publisher = _only_compose_qualification_decision_authority(
        layout.research_root
    )
    runtime_generation_root = args.runtime_generation_authority_root or layout.root / "runtime-generations"
    runtime_generation_root.mkdir(parents=True, exist_ok=True)
    runtime_generations = OnlyRuntimeGenerationRegistry(runtime_generation_root)
    generation_builder = OnlyRuntimeGenerationBuilder(
        OnlyLocalImmutableArtifactStore(runtime_generation_root / "artifacts"),
        Path(sys.executable),
    )
    generation_host = OnlyHistoricalGenerationHostManager(
        registry=runtime_generations,
        builder=generation_builder,
        cache_root=runtime_generation_root / "host-cache",
    )
    exact_catalog_reader = OnlyRuntimeGenerationExactCatalogDescriptorReader(
        runtime_generations,
        generation_builder,
        runtime_generation_root / "catalog-context-cache",
    )
    exact_catalog = OnlyExactCatalogContextQueryService(
        exact_catalog_reader,
        exact_catalog_reader,
        exact_catalog_reader,
        exact_catalog_reader,
    )
    run_store = OnlyPostgresResearchRunStore(postgres.dsn, operational_options)
    private_assets = OnlyPostgresPrivateAssetStore(postgres.dsn, operational_options)
    private_asset_revisions = OnlyPrivateAssetRevisionBindingResolver(private_assets)
    authoring_generations = OnlyVerifiedAuthoringGenerationReader(
        OnlyAuthoringExecutionGenerationStore(
            args.authoring_generation_root or layout.research_root / "authoring-generations"
        ),
        private_asset_revisions,
    )
    product_commands = OnlyPostgresProductCommandAuthority(postgres.dsn, operational_options)
    calculations = OnlyCalculationRegistry()
    data_sources = OnlyDataSourceFactoryRegistry()
    brokers = OnlyBrokerFactoryRegistry()
    broker_fees = OnlyBrokerFeeContractRegistry()
    market_products = OnlyMarketProductFactoryRegistry()
    catalog = only_load_backtest_deployment_catalog(tuple(args.backtest_product_config))
    resources = only_load_backtest_market_product_resources(tuple(args.backtest_market_resource))
    deployment = OnlyResearchFrozenDeploymentCheck(
        OnlyResearchDeploymentCoherenceVerifier(
            OnlyResearchSemanticStoreIdentity(layout.research_root),
            OnlyPostgresResearchDeploymentStore(postgres.dsn, operational_options),
        )
    )
    dataset_store = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    verification = _ResearchProductVerification(
        OnlyResearchServiceReadinessProbe(
            schema_status=schema.status,
            deployment_check=deployment.assert_compatible,
            required_roots=(
                OnlyResearchRequiredRoot("artifact_root", layout.research_artifact_root, False),
                OnlyResearchRequiredRoot("backtest_evidence_root", layout.backtest_evidence_root, False),
                OnlyResearchRequiredRoot("dataset_root", layout.research_dataset_root, False),
                OnlyResearchRequiredRoot(
                    "economic_binding_root",
                    layout.research_dataset_economic_binding_root,
                    False,
                ),
                OnlyResearchRequiredRoot("user_data_root", layout.root, False),
            ),
            registry_check=lambda: _verify_product_registries(calculations, market_products, catalog, resources),
        )
    )
    kernel = OnlyAlphaKernelHost(
        authority_guard=OnlyPostgresKernelAuthorityGuard(operational_dsn),
        booters=(
            OnlyKernelLifecycleStep(
                "calculation_registry_composition",
                lambda: only_configure_product_registries(
                    calculations,
                    data_sources,
                    brokers,
                    broker_fees,
                    market_products,
                ),
            ),
            OnlyKernelLifecycleStep(
                "qualification_policy_admission",
                lambda: _load_qualification_policies(tuple(args.qualification_policy), qualification_policies),
            ),
        ),
        verifiers=(
            OnlyKernelLifecycleStep(
                "postgres_server_compatibility",
                lambda: _verify_postgres_server(operational_dsn),
            ),
            OnlyKernelLifecycleStep("research_product_scope", verification.verify),
        ),
        recoverers=(
            OnlyKernelLifecycleStep(
                "strategy_projection_reconciliation",
                lambda: _reconcile_strategy_projections(layout, postgres.dsn),
            ),
        ),
    )
    try:
        startup_status = kernel.start()
    except OnlyKernelHostError as error:
        startup_status = kernel.status
        if startup_status.failure != error.failure:
            raise RuntimeError("Product Kernel failure evidence diverged from lifecycle status") from error
    if startup_status.state not in {OnlyKernelState.READY, OnlyKernelState.FAILED}:
        raise RuntimeError("Product Kernel startup did not reach a closed outcome")
    try:
        resolver = OnlyResearchSpecificationResolver(calculations)
        admission = OnlyResearchRunAdmissionService(
            resolver=resolver,
            dataset_store=dataset_store,
            now_utc=only_system_utc_now,
            authoring_generation_resolver=authoring_generations,
        )
        readiness = OnlyKernelResearchReadinessProjection(kernel, verification.evidence)
        artifact_reader = OnlyResearchArtifactProfileReader(layout.research_artifact_root)
        definition_resolver = OnlyResearchDefinitionResolver(calculations, dataset_store)
        calculation_results = OnlyParquetResearchCalculationResultStore(
            layout.research_calculation_result_root,
            dataset_store,
        )
        execution_evidence = OnlyResearchCalculationExecutionEvidenceStore(layout.research_root)
        legacy_statistics_results = OnlyParquetResearchStatisticsResultStore(
            layout.research_statistics_result_root,
            calculation_results,
        )
        factor_pair_statistics_results = OnlyParquetResearchFactorPairStatisticsResultStore(
            layout.research_statistics_result_root,
            calculation_results,
        )
        summary_statistics_results = OnlyJsonResearchSummaryStatisticsResultStore(
            layout.research_statistics_result_root,
            legacy_statistics_results,
            factor_pair_source_store=factor_pair_statistics_results,
        )
        statistics_results = OnlyResearchStatisticsResultReader(
            layout.research_statistics_result_root,
            legacy_statistics_results,
            summary_statistics_results,
            factor_pair_statistics_results,
        )
        research_results = OnlyJsonResearchResultStore(
            layout.research_result_root,
            statistics_results,
            calculation_results,
        )
        symbolic_store = OnlyJsonSymbolicSearchStore(layout.research_root)
        parameter_store = OnlyJsonParameterSearchStore(layout.research_root)
        search_catalogs = _GenerationOwnedCatalogReader()
        symbolic_contexts = OnlySymbolicSearchContextResolver(
            symbolic_store=symbolic_store,
            catalogs=cast(Any, search_catalogs),
            datasets=dataset_store,
            research_calculation_registry=calculations,
        )
        parameter_contexts = OnlyParameterSearchContextResolver(
            parameter_store=parameter_store,
            evaluations=symbolic_store,
            catalogs=cast(Any, search_catalogs),
            datasets=dataset_store,
            research_calculation_registry=calculations,
        )
        search_provenance_authority = OnlyJsonSearchProvenanceStore(
            layout.research_root,
            catalogs=cast(Any, search_catalogs),
            datasets=dataset_store,
            search_contexts=cast(Any, _SearchContextReader(symbolic_contexts, parameter_contexts)),
        )
        memory_revisions = OnlyExperimentMemoryRevisionStore(layout.experiment_memory_projection_root)
        memory_builder, advisory_builder = _compose_experiment_memory_projection_builder(
            layout=layout,
            postgres_dsn=postgres.dsn,
            search=search_provenance_authority,
            results=research_results,
            statistics=legacy_statistics_results,
            factor_pair_statistics=factor_pair_statistics_results,
            summary_statistics=summary_statistics_results,
            qualification_decisions=qualification_decisions,
            datasets=dataset_store,
            catalogs=exact_catalog_reader,
            calculations=calculation_results,
            runtime_generations=runtime_generations,
            authoring_generations=authoring_generations,
        )
        runtime_generation_resolver = OnlyResearchHostedRuntimeGenerationResolver(
            execution=generation_host,
            dataset_store_root=str(layout.research_dataset_root),
        )
        near_duplicate_queries = OnlyResearchNearDuplicateQueryService(
            specification_resolver=resolver,
            subject_resolver=OnlyExactEvaluationIntentResolverV1(
                runtime_generations=runtime_generations,
                runtime_resolution=runtime_generation_resolver,
                authoring_generations=authoring_generations,
            ),
            advisory_builder=advisory_builder,
            threshold_policy=OnlyNearDuplicateThresholdPolicyV1(
                "structured-default", "1", Decimal("0.5"), Decimal("0.8"), 10
            ),
        )
        command = OnlyResearchCommandService(
            admission=admission,
            store=run_store,
            now_utc=only_system_utc_now,
            runtime_generations=runtime_generations,
            command_admissions=product_commands,
            runtime_generation_resolver=runtime_generation_resolver,
            authoring_generation_reader=authoring_generations,
            novelty_decisions=OnlyNoveltyDecisionAuthority(layout.research_root),
            memory_builder=memory_builder,
            memory_revisions=memory_revisions,
        )
        strategy_compositions = OnlyPostgresPrivateStrategyResearchCompositionStore(postgres.dsn, operational_options)
        strategy_research_composer = OnlyPrivateStrategyResearchComposer(
            private_assets,
            OnlyQuantAssetCatalogGeneration(()),
        )
        strategy_research = OnlyPrivateStrategyResearchApplicationService(
            composer=strategy_research_composer,
            compositions=strategy_compositions,
            research=command,
            runtime_generations=runtime_generations,
            runtime_definition_resolver=runtime_generation_resolver,
        )
        research_queries = OnlyResearchRunQueryService(run_store)
        if startup_status.state is OnlyKernelState.FAILED:
            unavailable = _UnavailableProductAuthority()
            strategy_freeze = cast(OnlyStrategyFreezeProductService, unavailable)
            strategy_promotion = cast(OnlyStrategyPromotionProductService, unavailable)
            strategy_query = cast(OnlyStrategyQueryService, unavailable)
            qualification = cast(OnlyQualificationProductService, unavailable)
            qualification_query = cast(OnlyQualificationQueryService, unavailable)
            backtest_commands = cast(OnlyBacktestCommandService, unavailable)
            backtest_queries = cast(OnlyBacktestQueryService, unavailable)
            backtest_store = OnlyPostgresBacktestStore(postgres.dsn, operational_options)
            search_commands = None
            search_queries = None
            search_provenance = None
        else:
            semantic_namespace_id = OnlyResearchSemanticStoreIdentity(layout.research_root).load_verified()
            strategy_store = OnlyPostgresStrategyProductStore(
                postgres.dsn,
                semantic_namespace_id,
                operational_options,
            )
            frozen_strategies = OnlyFrozenStrategyRevisionStore(layout.research_root)
            freeze = OnlyStrategyFreezeApplicationService.compose(
                semantic_root=layout.research_root,
                postgres_dsn=postgres.dsn,
                semantic_namespace_id=semantic_namespace_id,
                runs=run_store,
                research_results=research_results,
                calculation_results=calculation_results,
                datasets=dataset_store,
                specification_resolver=resolver,
                calculations=calculations,
                audit_time=only_system_utc_now,
                strategy_composition_verifier=OnlyPrivateStrategyResearchCompositionVerifier(
                    strategy_research_composer,
                    strategy_compositions,
                    execution_evidence=execution_evidence,
                    runtime_generations=runtime_generations,
                    runtime_definition_resolver=runtime_generation_resolver,
                ),
                runtime_trading_resolver=runtime_generation_resolver,
            )
            strategy_freeze = OnlyStrategyFreezeProductService(
                freeze=freeze,
                strategies=frozen_strategies,
                store=strategy_store,
                now_utc=only_system_utc_now,
            )
            qualification_evaluator = OnlyQualificationEvaluator(
                strategies=frozen_strategies,
                policies=qualification_policies,
                research_results=research_results,
                backtest_evidence=OnlyBacktestEvidenceStore(layout.root),
                decisions=qualification_decision_publisher,
                research_statistics=statistics_results,
            )
            qualification = OnlyQualificationProductService(
                evaluator=qualification_evaluator,
                decisions=qualification_decisions,
                store=strategy_store,
                now_utc=only_system_utc_now,
            )
            qualification_query = OnlyQualificationQueryService(
                qualification_policies,
                qualification_decisions,
            )
            strategy_promotion = OnlyStrategyPromotionProductService(
                strategies=frozen_strategies,
                store=strategy_store,
                qualification_decisions=qualification_decisions,
                qualification_policies=qualification_policies,
                audit_time=only_system_utc_now,
            )
            strategy_query = OnlyStrategyQueryService(frozen_strategies, strategy_store)
            backtest_commands, backtest_queries, backtest_store = _compose_backtest_product(
                postgres.dsn,
                operational_options,
                layout,
                market_products,
                catalog,
                resources,
                runtime_generations,
            )
            search_commands, search_queries, search_provenance = _compose_search_product(
                layout=layout,
                calculations=calculations,
                datasets=dataset_store,
                research_commands=command,
                research_runs=research_queries,
                research_results=research_results,
                statistics_results=statistics_results,
                calculation_results=calculation_results,
                legacy_statistics_results=legacy_statistics_results,
                summary_statistics_results=summary_statistics_results,
                product_commands=product_commands,
                runtime_generations=runtime_generations,
                generation_host=generation_host,
                symbolic=symbolic_store,
                parameter=parameter_store,
                symbolic_contexts=symbolic_contexts,
                parameter_contexts=parameter_contexts,
                provenance=search_provenance_authority,
            )
        product_boundary = only_compose_research_product_boundary(
            admission=kernel,
            commands=command,
            queries=research_queries,
            exact_catalog_context=exact_catalog,
            search_commands=search_commands,
            search_queries=search_queries,
            near_duplicate_queries=near_duplicate_queries,
            strategy_research=strategy_research,
        )
        app = create_product_app(
            artifact_reader,
            product_boundary,
            calculations,
            definition_resolver,
            readiness,
            strategy_freeze,
            strategy_promotion,
            strategy_query,
            qualification,
            qualification_query,
            backtest_commands,
            backtest_queries,
            backtest_store,
            exact_catalog_context=exact_catalog,
            search_product=(None if search_commands is None else OnlySearchProductHttpServiceV1(product_boundary)),
            exact_dataset_snapshots=dataset_store,
            exact_evaluation_contexts=OnlyJsonSymbolicSearchStore(layout.research_root),
            agent_gateway=(
                None
                if args.agent_node_url is None
                else OnlyAgentNodeHttpGatewayV1(
                    OnlyAgentNodeGatewayConfigV1(
                        args.agent_node_url,
                        args.agent_control_token_file.read_text(encoding="utf-8").strip(),
                    )
                )
            ),
            runtime_generations=runtime_generations,
            search_authoring_inputs=_SearchAuthoringInputReader(
                OnlyJsonSymbolicSearchStore(layout.research_root),
                OnlyJsonParameterSearchStore(layout.research_root),
            ),
            exact_statistics=statistics_results,
            exact_search_iteration_results=search_provenance,
            exact_search_terminal_projections=_SearchTerminalProjectionReader(
                OnlyJsonSymbolicSearchStore(layout.research_root),
                OnlyJsonParameterSearchStore(layout.research_root),
            ),
            near_duplicate_advisory=near_duplicate_queries,
        )
        if startup_status.state is OnlyKernelState.READY:
            app.state.experiment_memory_projection_builder = memory_builder
        uvicorn.run(app, host=args.host, port=args.port)
    finally:
        generation_host.close()
        if kernel.state is OnlyKernelState.READY:
            kernel.stop()
    return 0


if __name__ == "__main__":  # pragma: no cover - console-script fallback
    raise SystemExit(main())
