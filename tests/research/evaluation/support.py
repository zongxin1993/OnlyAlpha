from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from onlyalpha_example_alpha.registration import registrations as factor_registrations
from onlyalpha_plugin_indicators.registration import registrations as indicator_registrations
from onlyalpha_plugin_operators.registration import registrations as operator_registrations
from onlyalpha_plugin_targets.registration import registrations as target_registrations
from onlyalpha_plugin_targets.registration import resolve_forward_return

from onlyalpha.calculation import (
    OnlyCalculationGraphDefinition,
    OnlyCalculationNodeDefinition,
    OnlyCalculationReference,
    OnlyCalculationRegistry,
)
from onlyalpha.research import (
    OnlyJsonResearchSummaryStatisticsResultStore,
    OnlyParquetResearchCalculationResultStore,
    OnlyParquetResearchDatasetSnapshotStore,
    OnlyParquetResearchFactorPairStatisticsResultStore,
    OnlyParquetResearchStatisticsResultStore,
    OnlyResearchCalculationBackendResolver,
    OnlyResearchCalculationExecutionEvidenceStore,
    OnlyResearchCalculationExecutor,
    OnlyResearchCoverageSummaryDefinition,
    OnlyResearchCoverageSummaryExecutor,
    OnlyResearchCoverageSummaryPlan,
    OnlyResearchEffectSummaryDefinition,
    OnlyResearchEffectSummaryExecutor,
    OnlyResearchEffectSummaryPlan,
    OnlyResearchFactorPairOperand,
    OnlyResearchFactorPairStatisticsDefinition,
    OnlyResearchFactorPairStatisticsExecutor,
    OnlyResearchFactorPairStatisticsMethod,
    OnlyResearchFactorPairStatisticsPlan,
    OnlyResearchFeatureSeriesReference,
    OnlyResearchJobExecutor,
    OnlyResearchJobPlan,
    OnlyResearchStatisticsDefinition,
    OnlyResearchStatisticsExecutor,
    OnlyResearchStatisticsMethod,
    OnlyResearchStatisticsPlan,
    OnlyResearchTargetSeriesReference,
    OnlyResearchTemporalSlice,
    OnlyResearchTemporalStabilityDefinition,
    OnlyResearchTemporalStabilityExecutor,
    OnlyResearchTemporalStabilityPlan,
)
from tests.research.calculation.support import snapshot
from tests.research.factor.support import factor_graph


def evaluation_registry() -> OnlyCalculationRegistry:
    registry = OnlyCalculationRegistry()
    for registration in (
        *operator_registrations(),
        *indicator_registrations(),
        *factor_registrations(),
        *target_registrations(),
    ):
        registry.register(registration)
    return registry


def target_graph(
    *, entry_source: str = "bar.close", entry_offset: int = 0, exit_offset: int = 1
) -> OnlyCalculationGraphDefinition:
    definition = resolve_forward_return(
        {"entry_offset": entry_offset, "exit_offset": exit_offset},
        OnlyCalculationReference(None, "entry_price", entry_source),
        OnlyCalculationReference(None, "exit_price", "bar.close"),
    )
    return OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(definition),))


def evaluation_case(root: Path):
    dataset_store = OnlyParquetResearchDatasetSnapshotStore(root / "datasets")
    candidate, partitions = snapshot()
    committed_dataset = dataset_store.commit(candidate, partitions)
    calculation_executor = OnlyResearchCalculationExecutor(
        dataset_store, OnlyResearchCalculationBackendResolver(evaluation_registry())
    )
    calculation_store = OnlyParquetResearchCalculationResultStore(
        root / "calculation-results",
        dataset_store,
        audit_time=lambda: datetime(2026, 8, 15, tzinfo=UTC),
    )
    job = OnlyResearchJobExecutor(
        calculation_executor,
        calculation_store,
        OnlyResearchCalculationExecutionEvidenceStore(root / "semantic"),
    )
    feature_graph = factor_graph()
    target = target_graph()
    feature_plan = OnlyResearchJobPlan(committed_dataset.snapshot_fingerprint, feature_graph)
    target_plan = OnlyResearchJobPlan(committed_dataset.snapshot_fingerprint, target)
    feature_outcome = job.execute(feature_plan)
    target_outcome = job.execute(target_plan)
    feature_node = next(
        node for node in feature_graph.ordered_nodes if node.definition.type_id == "example.factor.momentum"
    )
    target_node = target.ordered_nodes[0]
    statistics_plan = OnlyResearchStatisticsPlan(
        OnlyResearchFeatureSeriesReference(
            feature_outcome.calculation_fingerprint, feature_node.fingerprint, "factor_value"
        ),
        OnlyResearchTargetSeriesReference(
            target_outcome.calculation_fingerprint, target_node.fingerprint, "target_value"
        ),
        OnlyResearchStatisticsDefinition(method=OnlyResearchStatisticsMethod.IC),
    )
    return (
        committed_dataset,
        calculation_executor,
        calculation_store,
        job,
        feature_plan,
        target_plan,
        statistics_plan,
        dataset_store,
    )


def statistics_case(root: Path):
    case = evaluation_case(root)
    calculation_store = case[2]
    statistics_plan = case[6]
    statistics_store = OnlyParquetResearchStatisticsResultStore(
        root / "statistics-results",
        calculation_store,
        audit_time=lambda: datetime(2026, 8, 15, tzinfo=UTC),
    )
    executor = OnlyResearchStatisticsExecutor(calculation_store, statistics_store)
    return (*case, statistics_store, executor, executor.execute(statistics_plan))


def factor_pair_case(
    root: Path,
    method: OnlyResearchFactorPairStatisticsMethod = OnlyResearchFactorPairStatisticsMethod.FACTOR_CORRELATION,
):
    case = evaluation_case(root)
    committed_dataset, calculation_store, job, first_plan = case[0], case[2], case[3], case[4]
    second_graph = factor_graph(direction="LOWER_IS_BETTER")
    second_plan = OnlyResearchJobPlan(committed_dataset.snapshot_fingerprint, second_graph)
    first_outcome = job.execute(first_plan)
    second_outcome = job.execute(second_plan)
    first_node = next(
        node
        for node in first_plan.calculation_graph.ordered_nodes
        if node.definition.type_id == "example.factor.momentum"
    )
    second_node = next(
        node for node in second_graph.ordered_nodes if node.definition.type_id == "example.factor.momentum"
    )
    first_operand = OnlyResearchFactorPairOperand(
        "a" * 64,
        OnlyResearchFeatureSeriesReference(
            first_outcome.calculation_fingerprint, first_node.fingerprint, "factor_value"
        ),
    )
    second_operand = OnlyResearchFactorPairOperand(
        "b" * 64,
        OnlyResearchFeatureSeriesReference(
            second_outcome.calculation_fingerprint, second_node.fingerprint, "factor_value"
        ),
    )
    plan = OnlyResearchFactorPairStatisticsPlan(
        committed_dataset.snapshot_fingerprint,
        first_operand,
        second_operand,
        OnlyResearchFactorPairStatisticsDefinition(method),
    )
    store = OnlyParquetResearchFactorPairStatisticsResultStore(
        root / "statistics-results",
        calculation_store,
        audit_time=lambda: datetime(2026, 9, 5, tzinfo=UTC),
    )
    executor = OnlyResearchFactorPairStatisticsExecutor(calculation_store, store)
    outcome = executor.execute(plan)
    return (*case, second_plan, plan, store, executor, outcome)


def summary_case(root: Path, source_method: OnlyResearchStatisticsMethod = OnlyResearchStatisticsMethod.IC):
    case = statistics_case(root)
    source_store = case[8]
    source_plan = case[6]
    if source_method is not source_plan.definition.method:
        source_plan = OnlyResearchStatisticsPlan(
            source_plan.feature,
            source_plan.target,
            OnlyResearchStatisticsDefinition(source_method),
        )
        case[9].execute(source_plan)
    source = source_store.load_verified(source_plan.statistics_fingerprint)
    plan = OnlyResearchEffectSummaryPlan(
        source.manifest.dataset_snapshot_fingerprint,
        "c" * 64,
        source_plan.feature,
        source.manifest.statistics_fingerprint,
        source.manifest.statistics_result_fingerprint,
        OnlyResearchEffectSummaryDefinition(source_method),
    )
    summary_store = OnlyJsonResearchSummaryStatisticsResultStore(
        root / "statistics-results",
        source_store,
        audit_time=lambda: datetime(2026, 8, 15, tzinfo=UTC),
    )
    executor = OnlyResearchEffectSummaryExecutor(source_store, summary_store)
    return (*case, plan, summary_store, executor)


def coverage_case(root: Path, source_method: OnlyResearchStatisticsMethod = OnlyResearchStatisticsMethod.IC):
    case = statistics_case(root)
    source_store = case[8]
    source_plan = case[6]
    if source_method is not source_plan.definition.method:
        source_plan = OnlyResearchStatisticsPlan(
            source_plan.feature,
            source_plan.target,
            OnlyResearchStatisticsDefinition(source_method),
        )
        case[9].execute(source_plan)
    source = source_store.load_verified(source_plan.statistics_fingerprint)
    plan = OnlyResearchCoverageSummaryPlan(
        source.manifest.dataset_snapshot_fingerprint,
        "c" * 64,
        source_plan.feature,
        source.manifest.statistics_fingerprint,
        source.manifest.statistics_result_fingerprint,
        OnlyResearchCoverageSummaryDefinition(source_method),
    )
    summary_store = OnlyJsonResearchSummaryStatisticsResultStore(
        root / "statistics-results",
        source_store,
        audit_time=lambda: datetime(2026, 8, 15, tzinfo=UTC),
    )
    executor = OnlyResearchCoverageSummaryExecutor(source_store, summary_store)
    return (*case, plan, summary_store, executor)


def stability_case(
    root: Path,
    source_method: OnlyResearchStatisticsMethod = OnlyResearchStatisticsMethod.IC,
    intervals: tuple[OnlyResearchTemporalSlice, ...] = (
        OnlyResearchTemporalSlice(1767576600000000000, 1767576800000000000),
        OnlyResearchTemporalSlice(1767576800000000000, 1767576900000000000),
    ),
):
    case = statistics_case(root)
    source_store = case[8]
    source_plan = case[6]
    if source_method is not source_plan.definition.method:
        source_plan = OnlyResearchStatisticsPlan(
            source_plan.feature,
            source_plan.target,
            OnlyResearchStatisticsDefinition(source_method),
        )
        case[9].execute(source_plan)
    source = source_store.load_verified(source_plan.statistics_fingerprint)
    plan = OnlyResearchTemporalStabilityPlan(
        source.manifest.dataset_snapshot_fingerprint,
        "c" * 64,
        source_plan.feature,
        source.manifest.statistics_fingerprint,
        source.manifest.statistics_result_fingerprint,
        OnlyResearchTemporalStabilityDefinition(source_method),
        intervals,
    )
    summary_store = OnlyJsonResearchSummaryStatisticsResultStore(
        root / "statistics-results",
        source_store,
        audit_time=lambda: datetime(2026, 8, 15, tzinfo=UTC),
    )
    executor = OnlyResearchTemporalStabilityExecutor(source_store, summary_store)
    return (*case, plan, summary_store, executor)
