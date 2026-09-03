"""Explicit full Research API composition root."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import uvicorn

from onlyalpha.application.product_boundary import only_compose_research_product_boundary
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
    OnlyPostgresResearchDeploymentStore,
    OnlyPostgresResearchRunStore,
    OnlyPostgresSchemaVerifier,
    only_assert_supported_postgres_server,
)
from onlyalpha.persistence.postgres.backtest_store import OnlyPostgresBacktestStore
from onlyalpha.persistence.postgres.strategy_product_store import OnlyPostgresStrategyProductStore
from onlyalpha.research.artifact.reader import OnlyResearchArtifactProfileReader
from onlyalpha.research.calculation.result_store import OnlyParquetResearchCalculationResultStore
from onlyalpha.research.command.query import OnlyResearchRunQueryService
from onlyalpha.research.command.service import OnlyResearchCommandService
from onlyalpha.research.dataset import OnlyDatasetEconomicBindingStore, OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.definition.resolver import OnlyResearchDefinitionResolver
from onlyalpha.research.evaluation.result_store import OnlyParquetResearchStatisticsResultStore
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
from onlyalpha.research.result.result_store import OnlyJsonResearchResultStore
from onlyalpha.research.run.admission import OnlyResearchRunAdmissionService
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver
from onlyalpha.strategy.store import OnlyFrozenStrategyRevisionStore

from .app import create_product_app
from .composition import only_configure_product_registries
from .health import OnlyKernelResearchReadinessProjection


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


def _compose_backtest_product(
    postgres_dsn: str,
    operational_options: OnlyPostgresOperationalConnectionOptions,
    layout: OnlyUserDataLayout,
    market_products: OnlyMarketProductFactoryRegistry,
    catalog: OnlyBacktestDeploymentCatalog,
    resources: OnlyBacktestMarketProductResourceRegistry,
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
        OnlyBacktestCommandService(admission=admission, store=store, now_utc=only_system_utc_now),
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
        required=True,
        help="verified operator-owned Product configuration document; repeat for each Market Product",
    )
    parser.add_argument(
        "--backtest-market-resource",
        action="append",
        type=Path,
        default=[],
        help="verified plugin-owned Market Product resource document; repeat as required",
    )
    args = parser.parse_args(argv)
    postgres = OnlyPostgresConfig.from_environment()
    operational_options = OnlyPostgresOperationalConnectionOptions()
    operational_dsn = postgres.operational_dsn(operational_options)
    schema = OnlyPostgresSchemaVerifier(operational_dsn)
    layout = OnlyUserDataLayout(args.user_data_root)
    run_store = OnlyPostgresResearchRunStore(postgres.dsn, operational_options)
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
            run_store=run_store,
            now_utc=only_system_utc_now,
        )
        command = OnlyResearchCommandService(
            admission=admission,
            store=run_store,
            now_utc=only_system_utc_now,
        )
        product_boundary = only_compose_research_product_boundary(
            admission=kernel,
            commands=command,
            queries=OnlyResearchRunQueryService(run_store),
        )
        readiness = OnlyKernelResearchReadinessProjection(kernel, verification.evidence)
        artifact_reader = OnlyResearchArtifactProfileReader(layout.research_artifact_root)
        definition_resolver = OnlyResearchDefinitionResolver(calculations, dataset_store)
        if startup_status.state is OnlyKernelState.FAILED:
            unavailable = _UnavailableProductAuthority()
            strategy_freeze = cast(OnlyStrategyFreezeProductService, unavailable)
            strategy_promotion = cast(OnlyStrategyPromotionProductService, unavailable)
            strategy_query = cast(OnlyStrategyQueryService, unavailable)
            backtest_commands = cast(OnlyBacktestCommandService, unavailable)
            backtest_queries = cast(OnlyBacktestQueryService, unavailable)
            backtest_store = OnlyPostgresBacktestStore(postgres.dsn, operational_options)
        else:
            semantic_namespace_id = OnlyResearchSemanticStoreIdentity(layout.research_root).load_verified()
            strategy_store = OnlyPostgresStrategyProductStore(
                postgres.dsn,
                semantic_namespace_id,
                operational_options,
            )
            frozen_strategies = OnlyFrozenStrategyRevisionStore(layout.research_root)
            calculation_results = OnlyParquetResearchCalculationResultStore(
                layout.research_calculation_result_root,
                dataset_store,
            )
            statistics_results = OnlyParquetResearchStatisticsResultStore(
                layout.research_statistics_result_root,
                calculation_results,
            )
            research_results = OnlyJsonResearchResultStore(
                layout.research_result_root,
                statistics_results,
                calculation_results,
            )
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
            )
            strategy_freeze = OnlyStrategyFreezeProductService(
                freeze=freeze,
                strategies=frozen_strategies,
                store=strategy_store,
                now_utc=only_system_utc_now,
            )
            strategy_promotion = OnlyStrategyPromotionProductService(
                strategies=frozen_strategies,
                store=strategy_store,
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
            backtest_commands,
            backtest_queries,
            backtest_store,
        )
        uvicorn.run(app, host=args.host, port=args.port)
    finally:
        if kernel.state is OnlyKernelState.READY:
            kernel.stop()
    return 0


if __name__ == "__main__":  # pragma: no cover - console-script fallback
    raise SystemExit(main())
