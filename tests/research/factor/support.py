from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from onlyalpha_plugin_factors.registration import registrations as factor_registrations
from onlyalpha_plugin_factors.registration import resolve_momentum, resolve_percentile
from onlyalpha_plugin_indicators.registration import TYPES, resolve_definition
from onlyalpha_plugin_indicators.registration import registrations as indicator_registrations

from onlyalpha.calculation import (
    OnlyCalculationGraphDefinition,
    OnlyCalculationNodeDefinition,
    OnlyCalculationReference,
    OnlyCalculationRegistry,
)
from onlyalpha.research import (
    OnlyParquetResearchCalculationResultStore,
    OnlyParquetResearchDatasetSnapshotStore,
    OnlyResearchCalculationBackendResolver,
    OnlyResearchCalculationExecutor,
    OnlyResearchJobExecutor,
    OnlyResearchJobPlan,
)
from tests.research.calculation.support import snapshot


def factor_graph(direction: str = "HIGHER_IS_BETTER") -> OnlyCalculationGraphDefinition:
    rolling_return = next(item for item in TYPES if item.type_id == "onlyalpha.indicator.rolling_return")
    short = resolve_definition(rolling_return, {"period": 1})
    long = resolve_definition(rolling_return, {"period": 2})
    momentum = resolve_momentum(
        {"short_weight": "0.5", "long_weight": "0.5"},
        OnlyCalculationReference(short.fingerprint, "value"),
        OnlyCalculationReference(long.fingerprint, "value"),
    )
    scorer = resolve_percentile(
        {"direction": direction}, OnlyCalculationReference(momentum.fingerprint, "factor_value")
    )
    return OnlyCalculationGraphDefinition(
        tuple(OnlyCalculationNodeDefinition(item) for item in (scorer, momentum, long, short))
    )


def factor_registry() -> OnlyCalculationRegistry:
    registry = OnlyCalculationRegistry()
    for registration in (*indicator_registrations(), *factor_registrations()):
        registry.register(registration)
    return registry


def factor_case(root: Path):
    dataset_store = OnlyParquetResearchDatasetSnapshotStore(root / "datasets")
    candidate, partitions = snapshot()
    committed_dataset = dataset_store.commit(candidate, partitions)
    graph = factor_graph()
    calculation = OnlyResearchCalculationExecutor(
        dataset_store, OnlyResearchCalculationBackendResolver(factor_registry())
    )
    result_store = OnlyParquetResearchCalculationResultStore(
        root / "results", dataset_store, audit_time=lambda: datetime(2026, 8, 14, tzinfo=UTC)
    )
    plan = OnlyResearchJobPlan(committed_dataset.snapshot_fingerprint, graph)
    return plan, calculation, result_store, OnlyResearchJobExecutor(calculation, result_store)
