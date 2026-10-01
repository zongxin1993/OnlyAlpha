"""Deterministic official SMA workload for calculation-only publication tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from onlyalpha_plugin_indicators.registration import TYPES, resolve_definition

from onlyalpha.calculation import OnlyCalculationGraphDefinition, OnlyCalculationNodeDefinition
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.domain.market import OnlyBarSemantic, OnlyBarType
from onlyalpha.domain.value import OnlyPrice
from onlyalpha.engine import OnlyEngineConfig
from onlyalpha.engine.engine import OnlyEngine
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.research import OnlyParquetResearchDatasetSnapshotStore, OnlyResearchJobPlan
from onlyalpha.research.result.plan import (
    OnlyResearchResultCalculationPlan,
    OnlyResearchResultPlan,
    OnlyResearchResultSeriesPlan,
)
from onlyalpha.research.workload import OnlyResearchWorkloadPlan
from tests.research.calculation.support import bars, snapshot


def calculation_workload_case(root: Path, *, period: int = 2) -> tuple[OnlyEngine, OnlyResearchWorkloadPlan]:
    source = tuple(item for item in bars() if str(item.instrument_id) == "A.XNAS")
    values = tuple(
        replace(
            item,
            bar_type=OnlyBarType(item.instrument_id, OnlyBarSemantic.fixed_duration(15)),
            bar_start=source[0].bar_start + timedelta(minutes=15 * index),
            bar_end=source[0].bar_start + timedelta(minutes=15 * (index + 1)),
            ts_event=source[0].bar_start + timedelta(minutes=15 * (index + 1)),
            ts_init=source[0].bar_start + timedelta(minutes=15 * (index + 1)),
        )
        for index, item in enumerate(source)
    )
    values = (
        replace(values[0], open=OnlyPrice(Decimal(0), 2), close=OnlyPrice(Decimal(0), 2)),
        *values[1:],
    )
    candidate, partitions = snapshot(values)
    datasets = OnlyParquetResearchDatasetSnapshotStore(OnlyUserDataLayout(root).research_dataset_root)
    dataset = datasets.commit(candidate, partitions)
    registered = next(item for item in TYPES if item.type_id == "onlyalpha.indicator.sma")
    definition = resolve_definition(registered, {"period": period})
    graph = OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(definition),))
    job = OnlyResearchJobPlan(dataset.snapshot_fingerprint, graph)
    plan = OnlyResearchResultPlan(
        (),
        schema_version=3,
        dataset_snapshot_fingerprint=dataset.snapshot_fingerprint,
        calculations=(OnlyResearchResultCalculationPlan(job.calculation_fingerprint, graph.fingerprint),),
        published_series=(
            OnlyResearchResultSeriesPlan(None, job.calculation_fingerprint, definition.fingerprint, "value"),
        ),
    )
    workload = OnlyResearchWorkloadPlan((job,), (), (), plan)
    return OnlyEngine(OnlyEngineConfig(OnlyEngineId("calculation-publication"), root)), workload
