"""Verified exact-generation composition over the canonical Research Worker."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.persistence.postgres import (
    OnlyPostgresOperationalConnectionOptions,
    OnlyPostgresResearchExecutionStore,
    OnlyPostgresResearchRunStore,
)
from onlyalpha.research.artifact.reader import OnlyResearchArtifactProfileReader
from onlyalpha.research.calculation.execution_evidence import OnlyResearchCalculationExecutionEvidenceStore
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
from onlyalpha.research.result.result_store import OnlyJsonResearchResultStore
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver
from onlyalpha.runtime.defaults import OnlyEngineServices

from .generation import OnlyAuthoringExecutionGeneration, OnlyAuthoringExecutionGenerationStore


@dataclass(frozen=True, slots=True)
class OnlyAuthoringResearchWorkerComposition:
    """One process-lifetime generation and its canonical Worker service."""

    generation_fingerprint: str
    services: OnlyEngineServices
    resolver: OnlyResearchSpecificationResolver
    worker: OnlyResearchWorker
    service: OnlyResearchWorkerService


def only_compose_authoring_research_worker(
    *,
    generation: OnlyAuthoringExecutionGeneration,
    generation_store: OnlyAuthoringExecutionGenerationStore,
    user_data_root: Path,
    postgres_dsn: str,
    policy: OnlyResearchExecutionPolicy,
    now_utc: Callable[[], datetime],
    operational_options: OnlyPostgresOperationalConnectionOptions | None = None,
    polling_interval: timedelta = timedelta(seconds=1),
    worker_instance_id: OnlyResearchWorkerInstanceId | None = None,
) -> OnlyAuthoringResearchWorkerComposition:
    """Verify immutable generation evidence before constructing any claim-capable object."""

    generation_store.verify(generation)
    options = operational_options or OnlyPostgresOperationalConnectionOptions()
    options.assert_worker_compatible(
        heartbeat_interval=policy.heartbeat_interval,
        lease_duration=policy.lease_duration,
    )
    layout = OnlyUserDataLayout(user_data_root)
    services = generation.engine_services()
    resolver = OnlyResearchSpecificationResolver(services.assembler.components.calculations)
    dataset = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    calculation_results = OnlyParquetResearchCalculationResultStore(
        layout.research_calculation_result_root,
        dataset,
        audit_time=now_utc,
    )
    statistics_results = OnlyParquetResearchStatisticsResultStore(
        layout.research_statistics_result_root,
        calculation_results,
        audit_time=now_utc,
    )
    research_results = OnlyJsonResearchResultStore(
        layout.research_result_root,
        statistics_results,
        calculation_results,
    )
    execution_store = OnlyPostgresResearchExecutionStore(
        postgres_dsn,
        options,
        authoring_execution_generation_fingerprint=generation.fingerprint,
    )
    run_store = OnlyPostgresResearchRunStore(postgres_dsn, options)
    worker_id = worker_instance_id or OnlyResearchWorkerInstanceId.new()
    scheduler = OnlyResearchScheduler(store=execution_store, policy=policy, now_utc=now_utc)
    reconciler = OnlyResearchCancellationRecoveryReconciler(
        execution_store=execution_store,
        resolver=resolver,
        completion_probe=OnlyResearchVerifiedSemanticCompletionProbe(
            research_results,
            OnlyResearchArtifactProfileReader(layout.research_artifact_root),
            calculation_results,
            OnlyResearchCalculationExecutionEvidenceStore(layout.research_root),
        ),
        now_utc=now_utc,
    )
    worker = OnlyResearchWorker(
        worker_instance_id=worker_id,
        execution_store=execution_store,
        run_store=run_store,
        resolver=resolver,
        dataset_store=dataset,
        runtime_executor=OnlyEngineResearchRuntimeExecutor(layout.root, services),
        policy=policy,
        now_utc=now_utc,
        authoring_execution_generation_fingerprint=generation.fingerprint,
    )
    service = OnlyResearchWorkerService(
        scheduler=scheduler,
        worker=worker,
        cancellation_reconciler=reconciler,
        polling_interval=polling_interval,
    )
    return OnlyAuthoringResearchWorkerComposition(generation.fingerprint, services, resolver, worker, service)


__all__ = ["OnlyAuthoringResearchWorkerComposition", "only_compose_authoring_research_worker"]
