"""Explicit full Research API composition root."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.core.clock import only_system_utc_now
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.fee.broker_contract import OnlyBrokerFeeContractRegistry
from onlyalpha.market.product import OnlyMarketProductFactoryRegistry
from onlyalpha.output.user_data import OnlyUserDataLayout
from onlyalpha.persistence.postgres import (
    OnlyPostgresConfig,
    OnlyPostgresMigrationAuthority,
    OnlyPostgresOperationalConnectionOptions,
    OnlyPostgresResearchRunStore,
    only_assert_supported_postgres_server,
)
from onlyalpha.plugin.discovery import only_discover_plugins
from onlyalpha.research.artifact.reader import OnlyResearchArtifactProfileReader
from onlyalpha.research.command.query import OnlyResearchRunQueryService
from onlyalpha.research.command.service import OnlyResearchCommandService
from onlyalpha.research.dataset import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.definition.resolver import OnlyResearchDefinitionResolver
from onlyalpha.research.operations.readiness import OnlyResearchRequiredRoot, OnlyResearchServiceReadinessProbe
from onlyalpha.research.run.admission import OnlyResearchRunAdmissionService
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver

from .app import create_research_app


def _calculation_registry() -> OnlyCalculationRegistry:
    calculations = OnlyCalculationRegistry()
    only_discover_plugins(
        OnlyDataSourceFactoryRegistry(),
        OnlyBrokerFactoryRegistry(),
        OnlyBrokerFeeContractRegistry(),
        OnlyMarketProductFactoryRegistry(),
        calculations,
        fail_fast=True,
    )
    return calculations


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="onlyalpha-api")
    parser.add_argument("--user-data-root", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    postgres = OnlyPostgresConfig.from_environment()
    operational_options = OnlyPostgresOperationalConnectionOptions()
    operational_dsn = postgres.operational_dsn(operational_options)
    only_assert_supported_postgres_server(operational_dsn)
    OnlyPostgresMigrationAuthority(operational_dsn).assert_compatible()
    layout = OnlyUserDataLayout(args.user_data_root)
    for root in (layout.root, layout.research_dataset_root, layout.research_artifact_root):
        root.mkdir(parents=True, exist_ok=True)
    run_store = OnlyPostgresResearchRunStore(postgres.dsn, operational_options)
    calculations = _calculation_registry()
    dataset_store = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
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
    app = create_research_app(
        OnlyResearchArtifactProfileReader(layout.research_artifact_root),
        command,
        OnlyResearchRunQueryService(run_store),
        calculations,
        OnlyResearchDefinitionResolver(calculations, dataset_store),
        OnlyResearchServiceReadinessProbe(
            schema_status=lambda: OnlyPostgresMigrationAuthority(operational_dsn).status(),
            required_roots=(
                OnlyResearchRequiredRoot("artifact_root", layout.research_artifact_root, False),
                OnlyResearchRequiredRoot("dataset_root", layout.research_dataset_root, False),
                OnlyResearchRequiredRoot("user_data_root", layout.root, False),
            ),
            registry_check=lambda: None,
        ),
    )
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":  # pragma: no cover - console-script fallback
    raise SystemExit(main())
