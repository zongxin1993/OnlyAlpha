"""Production composition root for the durable Research Worker service."""

from __future__ import annotations

import argparse
import logging
import signal
from collections.abc import Sequence
from datetime import timedelta
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.core.clock import only_system_utc_now
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.fee.broker_contract import OnlyBrokerFeeContractRegistry
from onlyalpha.market.product import OnlyMarketProductFactoryRegistry
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.persistence.postgres import (
    OnlyPostgresConfig,
    OnlyPostgresMigrationAuthority,
    OnlyPostgresResearchExecutionStore,
    OnlyPostgresResearchOperationsStore,
    OnlyPostgresResearchRunStore,
    only_assert_supported_postgres_server,
)
from onlyalpha.plugin.discovery import only_discover_plugins
from onlyalpha.research.artifact.reader import OnlyResearchArtifactProfileReader
from onlyalpha.research.calculation.predicate import only_register_research_predicate_primitives
from onlyalpha.research.calculation.result_store import OnlyParquetResearchCalculationResultStore
from onlyalpha.research.dataset import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.evaluation.result_store import OnlyParquetResearchStatisticsResultStore
from onlyalpha.research.execution.model import OnlyResearchWorkerInstanceId
from onlyalpha.research.execution.policy import OnlyResearchExecutionPolicy
from onlyalpha.research.execution.reconciliation import (
    OnlyResearchCancellationRecoveryReconciler,
    OnlyResearchVerifiedSemanticCompletionProbe,
)
from onlyalpha.research.execution.scheduler import OnlyResearchScheduler
from onlyalpha.research.execution.worker import (
    OnlyEngineResearchRuntimeExecutor,
    OnlyResearchWorker,
    OnlyResearchWorkerService,
)
from onlyalpha.research.operations.logging import only_log_research_operational_event
from onlyalpha.research.operations.presence import OnlyResearchWorkerPresenceReporter
from onlyalpha.research.operations.readiness import OnlyResearchRequiredRoot, OnlyResearchServiceReadinessProbe
from onlyalpha.research.result.result_store import OnlyJsonResearchResultStore
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver

_LOG = logging.getLogger(__name__)


def _registry() -> OnlyCalculationRegistry:
    calculations = OnlyCalculationRegistry()
    only_discover_plugins(
        OnlyDataSourceFactoryRegistry(),
        OnlyBrokerFactoryRegistry(),
        OnlyBrokerFeeContractRegistry(),
        OnlyMarketProductFactoryRegistry(),
        calculations,
        fail_fast=True,
    )
    only_register_research_predicate_primitives(calculations)
    return calculations


def _service_version() -> str:
    try:
        return version("onlyalpha")
    except PackageNotFoundError:
        return "0+unknown"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="onlyalpha-research-worker")
    parser.add_argument("--user-data-root", type=Path, required=True)
    parser.add_argument("--polling-seconds", type=float, default=1.0)
    parser.add_argument("--lease-seconds", type=float, default=120.0)
    parser.add_argument("--heartbeat-seconds", type=float, default=30.0)
    parser.add_argument("--max-attempts", type=int, default=3)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    postgres = OnlyPostgresConfig.from_environment()
    only_assert_supported_postgres_server(postgres.dsn)
    migrations = OnlyPostgresMigrationAuthority(postgres.dsn)
    migrations.assert_compatible()
    layout = OnlyUserDataLayout(args.user_data_root)
    required_paths = (
        layout.root,
        layout.research_dataset_root,
        layout.research_calculation_result_root,
        layout.research_statistics_result_root,
        layout.research_result_root,
        layout.research_artifact_root,
    )
    for root in required_paths:
        root.mkdir(parents=True, exist_ok=True)
    calculations = _registry()
    readiness = OnlyResearchServiceReadinessProbe(
        schema_status=migrations.status,
        required_roots=tuple(
            OnlyResearchRequiredRoot(name, path, True)
            for name, path in zip(
                (
                    "user_data_root",
                    "dataset_root",
                    "calculation_root",
                    "statistics_root",
                    "result_root",
                    "artifact_root",
                ),
                required_paths,
                strict=True,
            )
        ),
        registry_check=lambda: None,
    )
    readiness.assert_ready()

    dataset = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    calculation_results = OnlyParquetResearchCalculationResultStore(
        layout.research_calculation_result_root, dataset, audit_time=only_system_utc_now
    )
    statistics_results = OnlyParquetResearchStatisticsResultStore(
        layout.research_statistics_result_root, calculation_results, audit_time=only_system_utc_now
    )
    research_results = OnlyJsonResearchResultStore(layout.research_result_root, statistics_results, calculation_results)
    artifact_reader = OnlyResearchArtifactProfileReader(layout.research_artifact_root)
    resolver = OnlyResearchSpecificationResolver(calculations)
    run_store = OnlyPostgresResearchRunStore(postgres.dsn)
    execution_store = OnlyPostgresResearchExecutionStore(postgres.dsn)
    operations_store = OnlyPostgresResearchOperationsStore(postgres.dsn)
    policy = OnlyResearchExecutionPolicy(
        lease_duration=timedelta(seconds=args.lease_seconds),
        heartbeat_interval=timedelta(seconds=args.heartbeat_seconds),
        max_attempts=args.max_attempts,
    )
    worker_id = OnlyResearchWorkerInstanceId.new()
    scheduler = OnlyResearchScheduler(store=execution_store, policy=policy, now_utc=only_system_utc_now)
    reconciler = OnlyResearchCancellationRecoveryReconciler(
        execution_store=execution_store,
        resolver=resolver,
        completion_probe=OnlyResearchVerifiedSemanticCompletionProbe(research_results, artifact_reader),
        now_utc=only_system_utc_now,
    )
    worker = OnlyResearchWorker(
        worker_instance_id=worker_id,
        execution_store=execution_store,
        run_store=run_store,
        resolver=resolver,
        dataset_store=dataset,
        runtime_executor=OnlyEngineResearchRuntimeExecutor(layout.root),
        policy=policy,
        now_utc=only_system_utc_now,
    )
    presence = OnlyResearchWorkerPresenceReporter(
        writer=operations_store,
        worker_instance_id=worker_id,
        service_version=_service_version(),
        heartbeat_interval=min(policy.heartbeat_interval, timedelta(seconds=15)),
    )
    service = OnlyResearchWorkerService(
        scheduler=scheduler,
        worker=worker,
        cancellation_reconciler=reconciler,
        polling_interval=timedelta(seconds=args.polling_seconds),
        presence_reporter=presence,
    )

    def drain(_signum: int, _frame: object) -> None:
        service.stop()

    signal.signal(signal.SIGINT, drain)
    signal.signal(signal.SIGTERM, drain)
    only_log_research_operational_event(
        _LOG,
        logging.INFO,
        "research.worker.started",
        worker_instance_id=str(worker_id),
        service_version=_service_version(),
    )
    service.run_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover - console-script fallback
    raise SystemExit(main())


__all__ = ["main"]
