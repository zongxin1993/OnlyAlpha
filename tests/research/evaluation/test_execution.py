from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest
from onlyalpha_plugin_targets.registration import resolve_forward_return

from onlyalpha.calculation import (
    OnlyCalculationGraphDefinition,
    OnlyCalculationNodeDefinition,
    OnlyCalculationReference,
)
from onlyalpha.research import (
    OnlyResearchFeatureSeriesReference,
    OnlyResearchJobDisposition,
    OnlyResearchJobPlan,
    OnlyResearchStatisticsDisposition,
    OnlyResearchSweepExecutor,
    OnlyResearchSweepPlanner,
    OnlyResearchTargetSeriesReference,
)
from onlyalpha.research.evaluation.errors import OnlyResearchEvaluationError
from tests.research.calculation.support import bars, reordered_snapshot, snapshot
from tests.research.evaluation.support import statistics_case
from tests.research.factor.support import factor_graph
from tests.research.sweep.support import definition as sweep_definition
from tests.research.sweep.support import registry as sweep_registry


def test_end_to_end_exact_alignment_pairwise_filtering_and_verified_reuse(tmp_path) -> None:
    case = statistics_case(tmp_path)
    plan, store, executor, first = case[6], case[8], case[9], case[10]
    assert first.disposition is OnlyResearchStatisticsDisposition.EXECUTED
    second = executor.execute(plan)
    assert second.disposition is OnlyResearchStatisticsDisposition.REUSED
    assert second.statistics_result_fingerprint == first.statistics_result_fingerprint
    result = store.load_verified(plan.statistics_fingerprint)
    assert tuple(row.sample_count for row in result.rows) == (0, 0, 2, 0)
    assert tuple(row.ts_event_ns for row in result.rows) == tuple(sorted(row.ts_event_ns for row in result.rows))


def test_multiple_feature_calculations_reuse_one_target_result(tmp_path) -> None:
    case = statistics_case(tmp_path)
    dataset, _, calculation_store, job, feature_plan, target_plan, statistics_plan = case[:7]
    statistics_executor = case[9]
    original_target = job.execute(target_plan)
    assert original_target.disposition is OnlyResearchJobDisposition.REUSED

    alternate_graph = factor_graph(direction="LOWER_IS_BETTER")
    alternate_feature = job.execute(OnlyResearchJobPlan(dataset.snapshot_fingerprint, alternate_graph))
    target_again = job.execute(target_plan)
    assert target_again.disposition is OnlyResearchJobDisposition.REUSED
    assert target_again.calculation_result_fingerprint == original_target.calculation_result_fingerprint
    alternate_node = next(
        node for node in alternate_graph.ordered_nodes if node.definition.type_id == "example.factor.momentum"
    )
    alternate_statistics = replace(
        statistics_plan,
        feature=OnlyResearchFeatureSeriesReference(
            alternate_feature.calculation_fingerprint, alternate_node.fingerprint, "factor_value"
        ),
    )
    assert alternate_statistics.feature.calculation_fingerprint != statistics_plan.feature.calculation_fingerprint
    assert alternate_statistics.target == statistics_plan.target
    alternate_outcome = statistics_executor.execute(alternate_statistics)
    assert alternate_outcome.disposition is OnlyResearchStatisticsDisposition.EXECUTED
    assert alternate_outcome.statistics_fingerprint != statistics_plan.statistics_fingerprint
    assert calculation_store.load_verified(
        target_plan.calculation_fingerprint
    ).manifest.calculation_result_fingerprint == (original_target.calculation_result_fingerprint)


def test_target_horizon_does_not_change_feature_calculation_identity(tmp_path) -> None:
    case = statistics_case(tmp_path)
    dataset, _, _, job, feature_plan = case[:5]
    feature_before = job.execute(feature_plan)
    target20 = resolve_forward_return(
        {"entry_offset": 0, "exit_offset": 20},
        OnlyCalculationReference(None, "entry_price", "bar.close"),
        OnlyCalculationReference(None, "exit_price", "bar.close"),
    )
    target20_plan = OnlyResearchJobPlan(
        dataset.snapshot_fingerprint,
        OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(target20),)),
    )
    job.execute(target20_plan)
    feature_after = job.execute(feature_plan)
    assert feature_after.calculation_fingerprint == feature_before.calculation_fingerprint
    assert feature_after.calculation_result_fingerprint == feature_before.calculation_result_fingerprint
    assert target20_plan.calculation_fingerprint != case[5].calculation_fingerprint


def test_target_result_is_instrument_order_neutral_and_verified_reload_is_exact(tmp_path) -> None:
    case = statistics_case(tmp_path)
    dataset_store, calculation_store, job, target_plan = case[7], case[2], case[3], case[5]
    candidate, partitions = reordered_snapshot()
    reordered = dataset_store.commit(candidate, partitions)
    assert reordered.snapshot_fingerprint == target_plan.dataset_snapshot_fingerprint
    outcome = job.execute(OnlyResearchJobPlan(reordered.snapshot_fingerprint, target_plan.calculation_graph))
    assert outcome.disposition is OnlyResearchJobDisposition.REUSED
    loaded = calculation_store.load_verified(outcome.calculation_fingerprint)
    assert loaded.manifest.calculation_result_fingerprint == outcome.calculation_result_fingerprint


def test_sweep_cells_compose_with_one_shared_target_and_distinct_statistics(tmp_path) -> None:
    case = statistics_case(tmp_path)
    dataset, job, target_plan, base_statistics, statistics_executor = case[0], case[3], case[5], case[6], case[9]
    sweep = OnlyResearchSweepPlanner(sweep_registry()).plan(
        sweep_definition(dataset.snapshot_fingerprint, candidates=(1, 3))
    )
    sweep_outcome = OnlyResearchSweepExecutor(job).execute(sweep)
    assert sweep_outcome.total_cells == 2
    target_result = job.execute(target_plan)
    assert target_result.disposition is OnlyResearchJobDisposition.REUSED
    statistics_fingerprints: list[str] = []
    for cell in sweep.cells:
        node = next(
            item
            for item in cell.calculation_graph.ordered_nodes
            if item.definition.type_id == "example.factor.momentum"
        )
        plan = replace(
            base_statistics,
            feature=OnlyResearchFeatureSeriesReference(cell.calculation_fingerprint, node.fingerprint, "factor_value"),
        )
        statistics_fingerprints.append(statistics_executor.execute(plan).statistics_fingerprint)
    assert len(set(statistics_fingerprints)) == 2
    assert job.execute(target_plan).calculation_result_fingerprint == target_result.calculation_result_fingerprint


def test_cross_dataset_evaluation_fails_closed_even_when_axes_match(tmp_path) -> None:
    case = statistics_case(tmp_path)
    dataset_store, job, statistics_plan, statistics_executor = case[7], case[3], case[6], case[9]
    changed_bars = list(bars())
    changed_bars[0] = replace(changed_bars[0], close=replace(changed_bars[0].close, value=Decimal("101")))
    candidate, partitions = snapshot(tuple(changed_bars))
    other_dataset = dataset_store.commit(candidate, partitions)
    other_target_plan = OnlyResearchJobPlan(other_dataset.snapshot_fingerprint, case[5].calculation_graph)
    other_target = job.execute(other_target_plan)
    other_target_node = other_target_plan.calculation_graph.ordered_nodes[0]
    mismatched = replace(
        statistics_plan,
        target=OnlyResearchTargetSeriesReference(
            other_target.calculation_fingerprint, other_target_node.fingerprint, "target_value"
        ),
    )
    with pytest.raises(OnlyResearchEvaluationError, match="STATISTICS_DATASET_MISMATCH"):
        statistics_executor.execute(mismatched)
