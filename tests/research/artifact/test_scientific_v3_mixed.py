from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from onlyalpha.research import (
    OnlyJsonResearchResultStore,
    OnlyParquetResearchScientificArtifactStoreV3,
    OnlyParquetResearchStatisticsResultStore,
    OnlyResearchCoverageSummaryDefinition,
    OnlyResearchCoverageSummaryExecutor,
    OnlyResearchCoverageSummaryPlan,
    OnlyResearchEffectSummaryDefinition,
    OnlyResearchEffectSummaryExecutor,
    OnlyResearchEffectSummaryPlan,
    OnlyResearchParameterNeighborhoodCandidateBinding,
    OnlyResearchParameterNeighborhoodSummaryDefinition,
    OnlyResearchParameterNeighborhoodSummaryExecutor,
    OnlyResearchParameterNeighborhoodSummaryPlan,
    OnlyResearchQueryError,
    OnlyResearchQueryErrorCode,
    OnlyResearchQueryService,
    OnlyResearchResultAssembler,
    OnlyResearchResultCalculationPlan,
    OnlyResearchResultCandidatePlan,
    OnlyResearchResultPlan,
    OnlyResearchScientificArtifactMaterializerV3,
    OnlyResearchStatisticsDefinition,
    OnlyResearchStatisticSeriesQuery,
    OnlyResearchStatisticsExecutor,
    OnlyResearchStatisticsMethod,
    OnlyResearchStatisticsPlan,
    OnlyResearchStatisticsResultReader,
    OnlyResearchTemporalSlice,
    OnlyResearchTemporalStabilityDefinition,
    OnlyResearchTemporalStabilityExecutor,
    OnlyResearchTemporalStabilityPlan,
    OnlyResearchTypedFactorPairSeriesDescriptor,
    OnlyResearchTypedStatisticSeriesQuery,
    OnlyResearchTypedStatisticsShape,
    OnlyResearchTypedStatisticSummaryQuery,
)
from onlyalpha.research.query.typed_model import (
    OnlyResearchCoverageSummaryProjection,
    OnlyResearchEffectSummaryProjection,
    OnlyResearchFactorPairEffectSummaryProjection,
    OnlyResearchParameterNeighborhoodSummaryProjection,
    OnlyResearchTemporalStabilitySummaryProjection,
)
from tests.research.evaluation.support import factor_pair_effect_case


def test_scientific_v3_complete_mixed_rich_product_verifies_offline(tmp_path) -> None:
    case = factor_pair_effect_case(tmp_path)
    pair_plan, pair_store = case[9], case[10]
    pair_effect_plan, summaries, pair_effect_executor = case[13], case[14], case[15]
    pair_effect_executor.execute(pair_effect_plan)
    legacy = OnlyParquetResearchStatisticsResultStore(
        tmp_path / "statistics-results",
        case[2],
        audit_time=lambda: datetime(2026, 9, 6, tzinfo=UTC),
    )
    legacy_executor = OnlyResearchStatisticsExecutor(case[2], legacy)
    ic_plan = case[6]
    rank_plan = OnlyResearchStatisticsPlan(
        ic_plan.feature,
        ic_plan.target,
        OnlyResearchStatisticsDefinition(OnlyResearchStatisticsMethod.RANK_IC),
    )
    legacy_executor.execute(ic_plan)
    legacy_executor.execute(rank_plan)
    source = legacy.load_verified(ic_plan.statistics_fingerprint)
    factor = pair_plan.first_operand.series
    focal_id, neighbor_ids = pair_plan.first_operand.candidate_fingerprint, ("d" * 64, "e" * 64)

    def make_effect(candidate_id: str) -> OnlyResearchEffectSummaryPlan:
        return OnlyResearchEffectSummaryPlan(
            source.manifest.dataset_snapshot_fingerprint,
            candidate_id,
            factor,
            source.manifest.statistics_fingerprint,
            source.manifest.statistics_result_fingerprint,
            OnlyResearchEffectSummaryDefinition(OnlyResearchStatisticsMethod.IC),
        )

    effects = (make_effect(focal_id), *(make_effect(x) for x in neighbor_ids))
    effect_executor = OnlyResearchEffectSummaryExecutor(legacy, summaries)
    for effect in effects:
        effect_executor.execute(effect)
    coverage = OnlyResearchCoverageSummaryPlan(
        source.manifest.dataset_snapshot_fingerprint,
        focal_id,
        factor,
        source.manifest.statistics_fingerprint,
        source.manifest.statistics_result_fingerprint,
        OnlyResearchCoverageSummaryDefinition(OnlyResearchStatisticsMethod.IC),
    )
    OnlyResearchCoverageSummaryExecutor(legacy, summaries).execute(coverage)
    stability = OnlyResearchTemporalStabilityPlan(
        source.manifest.dataset_snapshot_fingerprint,
        focal_id,
        factor,
        source.manifest.statistics_fingerprint,
        source.manifest.statistics_result_fingerprint,
        OnlyResearchTemporalStabilityDefinition(OnlyResearchStatisticsMethod.IC),
        (
            OnlyResearchTemporalSlice(1767576600000000000, 1767576800000000000),
            OnlyResearchTemporalSlice(1767576800000000000, 1767576900000000000),
        ),
    )
    OnlyResearchTemporalStabilityExecutor(legacy, summaries).execute(stability)
    assignments = (
        {"threshold": Decimal("0.1"), "window": 5},
        {"threshold": Decimal("0.2"), "window": 6},
        {"threshold": Decimal("0.3"), "window": 7},
    )
    bindings = tuple(
        OnlyResearchParameterNeighborhoodCandidateBinding(
            effect.subject_candidate_fingerprint,
            assignment,
            effect.statistics_fingerprint,
            summaries.load_verified(effect.statistics_fingerprint).manifest.statistics_result_fingerprint,
        )
        for effect, assignment in zip(effects, assignments, strict=True)
    )
    metric = "research.factor.ic.mean@1"
    neighborhood = OnlyResearchParameterNeighborhoodSummaryPlan(
        source.manifest.dataset_snapshot_fingerprint,
        metric,
        bindings[0],
        bindings[1:],
        OnlyResearchParameterNeighborhoodSummaryDefinition(metric),
    )
    OnlyResearchParameterNeighborhoodSummaryExecutor(summaries).execute(neighborhood)
    members = tuple(
        sorted(
            OnlyResearchResultCalculationPlan(
                operand.series.calculation_fingerprint,
                case[2].load_verified(operand.series.calculation_fingerprint).manifest.calculation_graph_fingerprint,
            )
            for operand in (pair_plan.first_operand, pair_plan.second_operand)
        )
    )
    by_calculation = {x.calculation_fingerprint: x for x in members}
    pair_membership = (pair_plan.statistics_fingerprint, pair_effect_plan.statistics_fingerprint)
    candidates = [
        OnlyResearchResultCandidatePlan(
            focal_id,
            "factor",
            tuple(sorted(assignments[0].items())),
            factor.calculation_fingerprint,
            by_calculation[factor.calculation_fingerprint].graph_fingerprint,
            (
                *pair_membership,
                effects[0].statistics_fingerprint,
                coverage.statistics_fingerprint,
                stability.statistics_fingerprint,
                neighborhood.statistics_fingerprint,
            ),
        ),
        OnlyResearchResultCandidatePlan(
            pair_plan.second_operand.candidate_fingerprint,
            "factor",
            (),
            pair_plan.second_operand.series.calculation_fingerprint,
            by_calculation[pair_plan.second_operand.series.calculation_fingerprint].graph_fingerprint,
            pair_membership,
        ),
    ]
    candidates.extend(
        OnlyResearchResultCandidatePlan(
            candidate_id,
            "factor",
            tuple(sorted(assignment.items())),
            factor.calculation_fingerprint,
            by_calculation[factor.calculation_fingerprint].graph_fingerprint,
            (effect.statistics_fingerprint,),
        )
        for candidate_id, assignment, effect in zip(neighbor_ids, assignments[1:], effects[1:], strict=True)
    )
    global_statistics = (
        ic_plan.statistics_fingerprint,
        rank_plan.statistics_fingerprint,
        pair_plan.statistics_fingerprint,
        pair_effect_plan.statistics_fingerprint,
        *(x.statistics_fingerprint for x in effects),
        coverage.statistics_fingerprint,
        stability.statistics_fingerprint,
        neighborhood.statistics_fingerprint,
    )
    result_plan = OnlyResearchResultPlan(
        global_statistics,
        2,
        source.manifest.dataset_snapshot_fingerprint,
        members,
        tuple(sorted(candidates)),
    )
    reader = OnlyResearchStatisticsResultReader(tmp_path / "statistics-results", legacy, summaries, pair_store)
    result = OnlyResearchResultAssembler(
        reader,
        calculation_result_store=case[2],
        audit_time=lambda: datetime(2026, 9, 6, tzinfo=UTC),
    ).assemble(result_plan)
    results = OnlyJsonResearchResultStore(tmp_path / "research-results", reader, case[2])
    results.commit(result)
    candidate = OnlyResearchScientificArtifactMaterializerV3(results, case[7], case[2], reader).materialize(
        result_plan.fingerprint
    )
    store = OnlyParquetResearchScientificArtifactStoreV3(tmp_path / "mixed-artifacts")
    store.commit(candidate)
    loaded = store.load_verified(result.manifest.research_result_fingerprint)

    assert {x.statistics_fingerprint for x in loaded.statistics_catalog} == set(global_statistics)
    assert len(loaded.statistics_summaries) == 7
    rich_entries = [x for x in loaded.statistics_catalog if hasattr(x.plan, "dataset_snapshot_fingerprint")]
    assert rich_entries
    assert all(
        entry.plan.dataset_snapshot_fingerprint
        == entry.dataset_snapshot_fingerprint
        == loaded.manifest.dataset_snapshot_fingerprint
        for entry in rich_entries
    )

    service = OnlyResearchQueryService(store)
    identity = loaded.manifest.research_result_fingerprint
    typed = service.list_typed_statistics(identity)
    assert tuple(item.statistics_fingerprint for item in typed.statistics) == tuple(sorted(global_statistics))
    assert len({item.statistics_fingerprint for item in typed.statistics}) == len(global_statistics)
    legacy_catalog = service.list_statistics(identity)
    assert {item.statistics_fingerprint for item in legacy_catalog.statistics} == {
        ic_plan.statistics_fingerprint,
        rank_plan.statistics_fingerprint,
    }
    for legacy_plan in (ic_plan, rank_plan):
        assert service.get_statistic_series(
            OnlyResearchStatisticSeriesQuery(identity, legacy_plan.statistics_fingerprint)
        ).points
    for rich_identity in (pair_plan.statistics_fingerprint, effects[0].statistics_fingerprint):
        with pytest.raises(OnlyResearchQueryError) as not_found:
            service.get_statistic_series(OnlyResearchStatisticSeriesQuery(identity, rich_identity))
        assert not_found.value.code is OnlyResearchQueryErrorCode.STATISTICS_NOT_FOUND
    assert {item.shape for item in typed.statistics} == {
        OnlyResearchTypedStatisticsShape.SERIES,
        OnlyResearchTypedStatisticsShape.SUMMARY,
    }
    pair_descriptor = next(
        item for item in typed.statistics if item.statistics_fingerprint == pair_plan.statistics_fingerprint
    )
    assert isinstance(pair_descriptor, OnlyResearchTypedFactorPairSeriesDescriptor)
    assert pair_descriptor.method == pair_plan.definition.method.value
    assert pair_descriptor.first_operand.candidate_fingerprint == pair_plan.first_operand.candidate_fingerprint
    assert pair_descriptor.second_operand.candidate_fingerprint == pair_plan.second_operand.candidate_fingerprint

    artifact_summary = service.get_artifact_summary(identity)
    assert artifact_summary.row_count == artifact_summary.statistics_series_row_count
    assert artifact_summary.series_statistics_count + artifact_summary.summary_statistics_count == len(
        global_statistics
    )
    assert artifact_summary.summary_statistics_count == len(loaded.statistics_summaries)
    assert {
        item.candidate_fingerprint: item.statistics_fingerprints
        for item in service.list_candidates(identity).candidates
    } == {item.candidate_fingerprint: item.statistics_fingerprints for item in loaded.manifest.plan.candidates}

    for series_plan in (ic_plan, rank_plan, pair_plan):
        expected = tuple(
            row
            for row in loaded.statistics_series_rows
            if row.statistics_fingerprint == series_plan.statistics_fingerprint
        )
        pages = []
        cursor = None
        while True:
            page = service.get_typed_statistic_series(
                OnlyResearchTypedStatisticSeriesQuery(
                    identity, series_plan.statistics_fingerprint, after_ts_event_ns=cursor, limit=1
                )
            )
            pages.extend(page.points)
            if not page.has_more:
                break
            cursor = page.next_after_ts_event_ns
        assert tuple((x.ts_event_ns, x.statistic_value, x.sample_count, x.status) for x in pages) == tuple(
            (x.ts_event_ns, x.statistic_value, x.sample_count, x.status) for x in expected
        )
        assert all(point.statistic_value is None or isinstance(point.statistic_value, Decimal) for point in pages)
        if len(expected) >= 2:
            filtered = service.get_typed_statistic_series(
                OnlyResearchTypedStatisticSeriesQuery(
                    identity,
                    series_plan.statistics_fingerprint,
                    from_ts_event_ns=expected[0].ts_event_ns,
                    to_ts_event_ns=expected[-1].ts_event_ns,
                    after_ts_event_ns=expected[0].ts_event_ns,
                )
            )
            assert tuple(x.ts_event_ns for x in filtered.points) == tuple(x.ts_event_ns for x in expected[1:-1])

    effect_projection = service.get_typed_statistic_summary(
        OnlyResearchTypedStatisticSummaryQuery(identity, effects[0].statistics_fingerprint)
    )
    coverage_projection = service.get_typed_statistic_summary(
        OnlyResearchTypedStatisticSummaryQuery(identity, coverage.statistics_fingerprint)
    )
    stability_projection = service.get_typed_statistic_summary(
        OnlyResearchTypedStatisticSummaryQuery(identity, stability.statistics_fingerprint)
    )
    pair_effect_projection = service.get_typed_statistic_summary(
        OnlyResearchTypedStatisticSummaryQuery(identity, pair_effect_plan.statistics_fingerprint)
    )
    neighborhood_projection = service.get_typed_statistic_summary(
        OnlyResearchTypedStatisticSummaryQuery(identity, neighborhood.statistics_fingerprint)
    )
    assert isinstance(effect_projection, OnlyResearchEffectSummaryProjection)
    assert isinstance(coverage_projection, OnlyResearchCoverageSummaryProjection)
    assert isinstance(stability_projection, OnlyResearchTemporalStabilitySummaryProjection)
    assert isinstance(pair_effect_projection, OnlyResearchFactorPairEffectSummaryProjection)
    assert isinstance(neighborhood_projection, OnlyResearchParameterNeighborhoodSummaryProjection)
    assert (
        effect_projection.mean.decimal_value
        == summaries.load_verified(effects[0].statistics_fingerprint).summary.mean.decimal_value
    )
    assert type(effect_projection.total_count.integer_value) is int
    assert (
        coverage_projection.pair_count_total.integer_value
        == summaries.load_verified(coverage.statistics_fingerprint).summary.pair_count_total.integer_value
    )
    assert tuple((x.start_ts_event_ns, x.end_ts_event_ns) for x in stability_projection.slices) == tuple(
        (x.start_ts_event_ns, x.end_ts_event_ns)
        for x in summaries.load_verified(stability.statistics_fingerprint).summary.slices
    )
    assert pair_effect_projection.source.statistics_fingerprint == pair_effect_plan.source_statistics_fingerprint
    assert tuple(item.candidate_fingerprint for item in neighborhood_projection.neighbors) == neighbor_ids
    assert neighborhood_projection.source_metric_id == metric
    for scalar in (
        effect_projection.mean,
        effect_projection.stddev_sample,
        coverage_projection.valid_timestamp_ratio,
        stability_projection.stddev_of_slice_means,
        pair_effect_projection.mean,
        neighborhood_projection.neighbor_stddev_sample,
    ):
        assert scalar.metric_id
        assert scalar.status.value
        if scalar.status.value != "VALID":
            assert scalar.integer_value is None and scalar.decimal_value is None

    for summary_identity in (effects[0].statistics_fingerprint, neighborhood.statistics_fingerprint):
        with pytest.raises(OnlyResearchQueryError) as mismatch:
            service.get_typed_statistic_series(OnlyResearchTypedStatisticSeriesQuery(identity, summary_identity))
        assert mismatch.value.code is OnlyResearchQueryErrorCode.STATISTICS_SHAPE_MISMATCH
    for series_identity in (ic_plan.statistics_fingerprint, pair_plan.statistics_fingerprint):
        with pytest.raises(OnlyResearchQueryError) as mismatch:
            service.get_typed_statistic_summary(OnlyResearchTypedStatisticSummaryQuery(identity, series_identity))
        assert mismatch.value.code is OnlyResearchQueryErrorCode.STATISTICS_SHAPE_MISMATCH
    with pytest.raises(OnlyResearchQueryError) as missing:
        service.get_typed_statistic_summary(OnlyResearchTypedStatisticSummaryQuery(identity, "f" * 64))
    assert missing.value.code is OnlyResearchQueryErrorCode.STATISTICS_NOT_FOUND

    script = """
import sys
from pathlib import Path
from onlyalpha.research import (
    OnlyResearchArtifactProfileReader, OnlyResearchQueryService,
    OnlyResearchTypedStatisticSeriesQuery, OnlyResearchTypedStatisticSummaryQuery,
)
service = OnlyResearchQueryService(OnlyResearchArtifactProfileReader(Path(sys.argv[1])))
identity, pair, effect, neighborhood = sys.argv[2:]
assert service.list_typed_statistics(identity).statistics
assert service.get_typed_statistic_series(OnlyResearchTypedStatisticSeriesQuery(identity, pair)).points
assert service.get_typed_statistic_summary(OnlyResearchTypedStatisticSummaryQuery(identity, effect)).mean.metric_id
assert service.get_typed_statistic_summary(OnlyResearchTypedStatisticSummaryQuery(identity, neighborhood)).neighbors
print("PASS")
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(tmp_path / "mixed-artifacts"),
            identity,
            pair_plan.statistics_fingerprint,
            effects[0].statistics_fingerprint,
            neighborhood.statistics_fingerprint,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout.strip() == "PASS"
