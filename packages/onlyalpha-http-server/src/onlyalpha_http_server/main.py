"""Explicit full Research API composition root."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from onlyalpha.application.product_boundary import only_compose_research_product_boundary
from onlyalpha.application.strategy_authority import (
    OnlyStrategyFreezeProjectionReconciliationApplicationService,
)
from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.core.clock import only_system_utc_now
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.fee.broker_contract import OnlyBrokerFeeContractRegistry
from onlyalpha.kernel import OnlyAlphaKernelHost, OnlyKernelHostError, OnlyKernelLifecycleStep, OnlyKernelState
from onlyalpha.market.product import OnlyMarketProductFactoryRegistry
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
from onlyalpha.plugin.discovery import only_discover_plugins
from onlyalpha.research.artifact.reader import OnlyResearchArtifactProfileReader
from onlyalpha.research.calculation.predicate import only_register_research_predicate_primitives
from onlyalpha.research.command.query import OnlyResearchRunQueryService
from onlyalpha.research.command.service import OnlyResearchCommandService
from onlyalpha.research.dataset import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.definition.resolver import OnlyResearchDefinitionResolver
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
from onlyalpha.research.run.admission import OnlyResearchRunAdmissionService
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver

from .app import create_research_app
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


def _verify_postgres_server(operational_dsn: str) -> None:
    only_assert_supported_postgres_server(operational_dsn)


def _configure_calculation_registry(calculations: OnlyCalculationRegistry) -> None:
    only_discover_plugins(
        OnlyDataSourceFactoryRegistry(),
        OnlyBrokerFactoryRegistry(),
        OnlyBrokerFeeContractRegistry(),
        OnlyMarketProductFactoryRegistry(),
        calculations,
        fail_fast=True,
    )
    only_register_research_predicate_primitives(calculations)


def _verify_calculation_registry(calculations: OnlyCalculationRegistry) -> None:
    calculations.type_definitions()


def _reconcile_strategy_projections(layout: OnlyUserDataLayout, postgres_dsn: str) -> None:
    semantic_namespace_id = OnlyResearchSemanticStoreIdentity(layout.research_root).load_verified()
    OnlyStrategyFreezeProjectionReconciliationApplicationService.compose(
        semantic_root=layout.research_root,
        postgres_dsn=postgres_dsn,
        semantic_namespace_id=semantic_namespace_id,
        audit_time=only_system_utc_now,
    ).reconcile_all()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="onlyalpha-http-server")
    parser.add_argument("--user-data-root", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    postgres = OnlyPostgresConfig.from_environment()
    operational_options = OnlyPostgresOperationalConnectionOptions()
    operational_dsn = postgres.operational_dsn(operational_options)
    schema = OnlyPostgresSchemaVerifier(operational_dsn)
    layout = OnlyUserDataLayout(args.user_data_root)
    run_store = OnlyPostgresResearchRunStore(postgres.dsn, operational_options)
    calculations = OnlyCalculationRegistry()
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
                OnlyResearchRequiredRoot("dataset_root", layout.research_dataset_root, False),
                OnlyResearchRequiredRoot("user_data_root", layout.root, False),
            ),
            registry_check=lambda: _verify_calculation_registry(calculations),
        )
    )
    kernel = OnlyAlphaKernelHost(
        authority_guard=OnlyPostgresKernelAuthorityGuard(operational_dsn),
        booters=(
            OnlyKernelLifecycleStep(
                "calculation_registry_composition",
                lambda: _configure_calculation_registry(calculations),
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
        app = create_research_app(
            OnlyResearchArtifactProfileReader(layout.research_artifact_root),
            product_boundary,
            calculations,
            OnlyResearchDefinitionResolver(calculations, dataset_store),
            OnlyKernelResearchReadinessProjection(kernel, verification.evidence),
        )
        uvicorn.run(app, host=args.host, port=args.port)
    finally:
        if kernel.state is OnlyKernelState.READY:
            kernel.stop()
    return 0


if __name__ == "__main__":  # pragma: no cover - console-script fallback
    raise SystemExit(main())
