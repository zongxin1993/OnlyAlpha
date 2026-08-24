from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from onlyalpha_plugin_indicators.registration import TYPES, registrations, resolve_definition

from onlyalpha.calculation import OnlyCalculationGraphDefinition, OnlyCalculationNodeDefinition, OnlyCalculationRegistry
from onlyalpha.research import (
    OnlyParquetResearchCalculationResultStore,
    OnlyParquetResearchDatasetSnapshotStore,
    OnlyResearchCalculationBackendResolver,
    OnlyResearchCalculationExecutionEvidenceStore,
    OnlyResearchCalculationExecutor,
    OnlyResearchJobExecutor,
    OnlyResearchJobPlan,
)
from tests.research.calculation.support import snapshot


def job_case(root: Path):
    dataset_store = OnlyParquetResearchDatasetSnapshotStore(root / "datasets")
    candidate, partitions = snapshot()
    committed_dataset = dataset_store.commit(candidate, partitions)
    registry = OnlyCalculationRegistry()
    for registration in registrations():
        registry.register(registration)
    definition = resolve_definition(TYPES[0], {"period": 2})
    graph = OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(definition),))
    calculation_executor = OnlyResearchCalculationExecutor(
        dataset_store,
        OnlyResearchCalculationBackendResolver(registry),
    )
    result_store = OnlyParquetResearchCalculationResultStore(
        root / "results",
        dataset_store,
        audit_time=lambda: datetime(2026, 8, 14, tzinfo=UTC),
    )
    evidence_store = OnlyResearchCalculationExecutionEvidenceStore(root / "semantic")
    result_store._test_execution_evidence_store = evidence_store
    plan = OnlyResearchJobPlan(committed_dataset.snapshot_fingerprint, graph)
    return plan, calculation_executor, result_store, research_job_executor(calculation_executor, result_store)


def research_job_executor(calculation, result_store) -> OnlyResearchJobExecutor:
    current = result_store
    while not hasattr(current, "_test_execution_evidence_store"):
        current = current.delegate
    return OnlyResearchJobExecutor(
        calculation,
        result_store,
        current._test_execution_evidence_store,
    )
