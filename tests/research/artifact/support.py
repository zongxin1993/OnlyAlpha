from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.research import (
    OnlyParquetResearchArtifactStore,
    OnlyParquetResearchCalculationResultStore,
    OnlyParquetResearchDatasetSnapshotStore,
    OnlyParquetResearchScientificArtifactStore,
    OnlyParquetResearchStatisticsResultStore,
    OnlyResearchArtifactMaterializer,
    OnlyResearchDefinitionResolver,
    OnlyResearchScientificArtifactMaterializer,
)
from onlyalpha.research.result.result_store import OnlyJsonResearchResultStore
from tests.research.calculation.support import snapshot
from tests.research.definition.support import definition
from tests.research.evaluation.support import evaluation_registry
from tests.research.result.support import result_case


def artifact_case(root: Path, *, year: int = 2026):
    plan, _, result_store, research_result, statistics_store = result_case(root)
    result_store.commit(research_result)
    materializer = OnlyResearchArtifactMaterializer(result_store, statistics_store)
    candidate = materializer.materialize(plan.fingerprint)
    store = OnlyParquetResearchArtifactStore(
        root / "research-artifacts",
        audit_time=lambda: datetime(year, 8, 16, tzinfo=UTC),
    )
    return plan, research_result, statistics_store, materializer, candidate, store


def artifact_target(root: Path, research_result_fingerprint: str) -> Path:
    return (
        root
        / "research-artifacts"
        / "research-statistics-v1"
        / "sha256"
        / research_result_fingerprint[:2]
        / research_result_fingerprint
    )


def scientific_artifact_case(root: Path):
    layout = OnlyUserDataLayout(root)
    datasets = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    dataset_candidate, partitions = snapshot()
    committed = datasets.commit(dataset_candidate, partitions)

    class Resolver:
        def resolve_verified(self, expected):  # type: ignore[no-untyped-def]
            value = datasets.load_verified_table(committed.snapshot_fingerprint)
            if value.snapshot.definition != expected:
                raise ValueError("Dataset mismatch")
            return value

    resolved = OnlyResearchDefinitionResolver(evaluation_registry(), Resolver()).resolve(
        definition(committed.definition)
    )
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("scientific-integrity"), root))
    runtime_id = engine.add_research_workload(resolved.workload)
    engine.initialize()
    engine.start()
    outcome = engine.run_runtime(runtime_id)
    engine.stop()
    assert outcome.research_result_fingerprint is not None

    calculations = OnlyParquetResearchCalculationResultStore(layout.research_calculation_result_root, datasets)
    statistics = OnlyParquetResearchStatisticsResultStore(layout.research_statistics_result_root, calculations)
    results = OnlyJsonResearchResultStore(layout.research_result_root, statistics, calculations)
    candidate = OnlyResearchScientificArtifactMaterializer(results, datasets, calculations, statistics).materialize(
        resolved.workload.result_plan.fingerprint
    )
    store = OnlyParquetResearchScientificArtifactStore(
        root / "scientific-artifacts",
        audit_time=lambda: datetime(2026, 8, 20, tzinfo=UTC),
    )
    return resolved, candidate, store


def scientific_artifact_target(root: Path, research_result_fingerprint: str) -> Path:
    return (
        root
        / "scientific-artifacts"
        / "research-scientific-v2"
        / "sha256"
        / research_result_fingerprint[:2]
        / research_result_fingerprint
    )
