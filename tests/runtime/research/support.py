from __future__ import annotations

from pathlib import Path

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngineConfig
from onlyalpha.engine.engine import OnlyEngine
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.research import (
    OnlyParquetResearchDatasetSnapshotStore,
    OnlyResearchFeatureSeriesReference,
    OnlyResearchJobPlan,
    OnlyResearchResultPlan,
    OnlyResearchStatisticsDefinition,
    OnlyResearchStatisticsMethod,
    OnlyResearchStatisticsPlan,
    OnlyResearchSweepCell,
    OnlyResearchSweepPlan,
    OnlyResearchTargetSeriesReference,
)
from onlyalpha.runtime.research import OnlyResearchWorkloadPlan
from tests.research.calculation.support import snapshot
from tests.research.evaluation.support import target_graph
from tests.research.factor.support import factor_graph


def workload_case(root: Path) -> tuple[OnlyEngine, OnlyResearchWorkloadPlan]:
    layout = OnlyUserDataLayout(root)
    dataset_store = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    candidate, partitions = snapshot()
    dataset = dataset_store.commit(candidate, partitions)
    feature = factor_graph()
    target = target_graph()
    feature_job = OnlyResearchJobPlan(dataset.snapshot_fingerprint, feature)
    target_job = OnlyResearchJobPlan(dataset.snapshot_fingerprint, target)
    feature_node = next(
        node for node in feature.ordered_nodes if node.definition.type_id == "onlyalpha.factor.momentum"
    )
    target_node = target.ordered_nodes[0]
    statistics = OnlyResearchStatisticsPlan(
        OnlyResearchFeatureSeriesReference(
            feature_job.calculation_fingerprint, feature_node.fingerprint, "factor_value"
        ),
        OnlyResearchTargetSeriesReference(target_job.calculation_fingerprint, target_node.fingerprint, "target_value"),
        OnlyResearchStatisticsDefinition(method=OnlyResearchStatisticsMethod.IC),
    )
    workload = OnlyResearchWorkloadPlan(
        (feature_job, target_job),
        (),
        (statistics,),
        OnlyResearchResultPlan((statistics.statistics_fingerprint,)),
    )
    return OnlyEngine(OnlyEngineConfig(OnlyEngineId("research-product"), root)), workload


def sweep_only_workload_case(root: Path) -> tuple[OnlyEngine, OnlyResearchWorkloadPlan]:
    layout = OnlyUserDataLayout(root)
    dataset_store = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    candidate, partitions = snapshot()
    dataset = dataset_store.commit(candidate, partitions)
    feature = factor_graph("LOWER_IS_BETTER")
    target = target_graph()
    feature_job = OnlyResearchJobPlan(dataset.snapshot_fingerprint, feature)
    target_job = OnlyResearchJobPlan(dataset.snapshot_fingerprint, target)
    feature_node = next(
        node for node in feature.ordered_nodes if node.definition.type_id == "onlyalpha.factor.momentum"
    )
    target_node = target.ordered_nodes[0]
    statistics = OnlyResearchStatisticsPlan(
        OnlyResearchFeatureSeriesReference(
            feature_job.calculation_fingerprint, feature_node.fingerprint, "factor_value"
        ),
        OnlyResearchTargetSeriesReference(target_job.calculation_fingerprint, target_node.fingerprint, "target_value"),
        OnlyResearchStatisticsDefinition(method=OnlyResearchStatisticsMethod.IC),
    )
    sweeps = (
        OnlyResearchSweepPlan((OnlyResearchSweepCell(0, (), feature, feature_job),)),
        OnlyResearchSweepPlan((OnlyResearchSweepCell(0, (), target, target_job),)),
    )
    workload = OnlyResearchWorkloadPlan(
        (),
        sweeps,
        (statistics,),
        OnlyResearchResultPlan((statistics.statistics_fingerprint,)),
    )
    return OnlyEngine(OnlyEngineConfig(OnlyEngineId("research-sweep-product"), root)), workload
