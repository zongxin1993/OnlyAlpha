from __future__ import annotations

from dataclasses import replace
from decimal import ROUND_DOWN, Decimal, Inexact, Rounded, localcontext

import pytest

from onlyalpha.research import (
    OnlyResearchFeatureSeriesReference,
    OnlyResearchStatisticRow,
    OnlyResearchStatisticsDisposition,
    OnlyResearchStatisticsMethod,
    OnlyResearchStatisticStatus,
    OnlyResearchSummaryScalarStatus,
    OnlyResearchTemporalSlice,
    OnlyResearchTemporalStabilityDefinition,
    OnlyResearchTemporalStabilityPlan,
    only_compute_research_temporal_stability,
    only_research_summary_plan_from_dict,
)
from onlyalpha.research.evaluation.errors import OnlyResearchEvaluationError
from tests.research.evaluation.support import stability_case


def _row(timestamp: int, value: str | None, status=OnlyResearchStatisticStatus.VALID):
    return OnlyResearchStatisticRow(timestamp, None if value is None else Decimal(value), 3, status)


def _source_with(source, rows):
    return replace(source, rows=tuple(rows))


def test_temporal_slice_and_plan_contract_are_exact_ordered_and_half_open() -> None:
    interval = OnlyResearchTemporalSlice(0, 100)
    assert OnlyResearchTemporalSlice.from_dict(interval.to_dict()) == interval
    for bounds in ((0, 0), (1, 0)):
        with pytest.raises(ValueError, match="start < end"):
            OnlyResearchTemporalSlice(*bounds)
    with pytest.raises(ValueError, match="integer"):
        OnlyResearchTemporalSlice(True, 1)

    definition = OnlyResearchTemporalStabilityDefinition(OnlyResearchStatisticsMethod.IC)
    base = dict(
        dataset_snapshot_fingerprint="a" * 64,
        subject_candidate_fingerprint="b" * 64,
        subject=OnlyResearchFeatureSeriesReference("c" * 64, "d" * 64, "factor_value"),
        source_statistics_fingerprint="e" * 64,
        source_statistics_result_fingerprint="f" * 64,
        definition=definition,
    )
    with pytest.raises(ValueError, match="non-empty"):
        OnlyResearchTemporalStabilityPlan(**base, intervals=())
    for intervals in (
        (OnlyResearchTemporalSlice(100, 200), OnlyResearchTemporalSlice(0, 100)),
        (OnlyResearchTemporalSlice(0, 101), OnlyResearchTemporalSlice(100, 200)),
        (OnlyResearchTemporalSlice(0, 100), OnlyResearchTemporalSlice(0, 100)),
    ):
        with pytest.raises(ValueError, match="ordered"):
            OnlyResearchTemporalStabilityPlan(**base, intervals=intervals)
    adjacent = OnlyResearchTemporalStabilityPlan(
        **base, intervals=(OnlyResearchTemporalSlice(0, 100), OnlyResearchTemporalSlice(100, 200))
    )
    assert OnlyResearchTemporalStabilityPlan.from_dict(adjacent.to_dict()) == adjacent
    assert only_research_summary_plan_from_dict(adjacent.to_dict()) == adjacent
    assert definition.to_dict() == {
        "schema_version": 1,
        "summary_kind": "TEMPORAL_STABILITY",
        "source_method": "IC",
        "interval_assignment": "HALF_OPEN_EXPLICIT",
        "source_status_policy": "VALID_ONLY_FOR_EFFECT",
        "standard_deviation": "SAMPLE",
        "information_ratio": "NON_ANNUALIZED",
        "sign_rule": "STRICT",
        "numeric": {
            "representation": "DECIMAL",
            "precision": 38,
            "output_quantum": "0.000000000001",
            "rounding": "ROUND_HALF_EVEN",
        },
        "decimal_execution_policy": "onlyalpha.decimal.execution@1",
    }


def test_half_open_boundaries_gap_exclusion_and_golden_aggregates(tmp_path) -> None:
    intervals = (
        OnlyResearchTemporalSlice(0, 100),
        OnlyResearchTemporalSlice(100, 200),
        OnlyResearchTemporalSlice(300, 400),
    )
    case = stability_case(tmp_path, intervals=intervals)
    source = case[8].load_verified(case[6].statistics_fingerprint)
    rows = (
        _row(99, "0.1"),
        _row(100, "0.2"),
        _row(150, "0.4"),
        _row(199, None, OnlyResearchStatisticStatus.INSUFFICIENT_OBSERVATIONS),
        _row(200, "0.9"),
        _row(250, "-0.9"),
    )
    summary = only_compute_research_temporal_stability(_source_with(source, rows), case[11])
    assert "stability_score" not in summary.to_dict()
    first, second, empty = summary.slices
    assert (first.total_timestamp_count, second.total_timestamp_count, empty.total_timestamp_count) == (1, 3, 0)
    assert first.mean.decimal_value == Decimal("0.100000000000")
    assert second.mean.decimal_value == Decimal("0.300000000000")
    assert second.valid_timestamp_ratio.decimal_value == Decimal("0.666666666667")
    assert empty.mean.status is OnlyResearchSummaryScalarStatus.NO_VALID_OBSERVATIONS
    assert empty.stddev_sample.status is OnlyResearchSummaryScalarStatus.INSUFFICIENT_OBSERVATIONS
    assert empty.information_ratio.status is OnlyResearchSummaryScalarStatus.INSUFFICIENT_OBSERVATIONS
    assert empty.valid_timestamp_ratio.status is OnlyResearchSummaryScalarStatus.NO_VALID_OBSERVATIONS
    assert summary.slice_count.integer_value == 3
    assert summary.valid_slice_count.integer_value == 2
    assert summary.positive_mean_slice_count.integer_value == 2
    assert summary.positive_mean_slice_ratio.decimal_value == Decimal("1.000000000000")
    assert summary.min_slice_mean.decimal_value == Decimal("0.100000000000")
    assert summary.max_slice_mean.decimal_value == Decimal("0.300000000000")
    assert summary.stddev_of_slice_means.decimal_value == Decimal("0.141421356237")


def test_all_invalid_and_single_valid_slice_semantics(tmp_path) -> None:
    case = stability_case(
        tmp_path,
        intervals=(OnlyResearchTemporalSlice(0, 10), OnlyResearchTemporalSlice(10, 20)),
    )
    source = case[8].load_verified(case[6].statistics_fingerprint)
    rows = (
        _row(1, None, OnlyResearchStatisticStatus.ZERO_VARIANCE_FEATURE),
        _row(2, None, OnlyResearchStatisticStatus.ZERO_VARIANCE_TARGET),
        _row(10, "-0.25"),
    )
    summary = only_compute_research_temporal_stability(_source_with(source, rows), case[11])
    invalid, single = summary.slices
    assert invalid.valid_timestamp_count == 0
    assert invalid.valid_timestamp_ratio.decimal_value == Decimal("0.000000000000")
    assert invalid.mean.status is OnlyResearchSummaryScalarStatus.NO_VALID_OBSERVATIONS
    assert single.mean.decimal_value == Decimal("-0.250000000000")
    assert single.stddev_sample.status is OnlyResearchSummaryScalarStatus.INSUFFICIENT_OBSERVATIONS
    assert single.information_ratio.status is OnlyResearchSummaryScalarStatus.INSUFFICIENT_OBSERVATIONS
    assert summary.valid_slice_count.integer_value == 1
    assert summary.negative_mean_slice_count.integer_value == 1
    assert summary.negative_mean_slice_ratio.decimal_value == Decimal("1.000000000000")
    assert summary.stddev_of_slice_means.status is OnlyResearchSummaryScalarStatus.INSUFFICIENT_OBSERVATIONS


def test_no_valid_slices_have_typed_absence_and_identical_means_have_zero_stddev(tmp_path) -> None:
    case = stability_case(tmp_path, intervals=(OnlyResearchTemporalSlice(0, 2), OnlyResearchTemporalSlice(2, 4)))
    source = case[8].load_verified(case[6].statistics_fingerprint)
    invalid = only_compute_research_temporal_stability(
        _source_with(source, (_row(0, None, OnlyResearchStatisticStatus.INSUFFICIENT_OBSERVATIONS),)), case[11]
    )
    for name in (
        "positive_mean_slice_ratio",
        "negative_mean_slice_ratio",
        "zero_mean_slice_ratio",
        "min_slice_mean",
        "max_slice_mean",
    ):
        assert getattr(invalid, name).status is OnlyResearchSummaryScalarStatus.NO_VALID_OBSERVATIONS
    assert invalid.stddev_of_slice_means.status is OnlyResearchSummaryScalarStatus.INSUFFICIENT_OBSERVATIONS

    equal = only_compute_research_temporal_stability(_source_with(source, (_row(0, "0.5"), _row(2, "0.5"))), case[11])
    assert equal.stddev_of_slice_means.status is OnlyResearchSummaryScalarStatus.VALID
    assert equal.stddev_of_slice_means.decimal_value == Decimal("0.000000000000")


def test_sign_and_cross_slice_stddev_use_published_slice_means(tmp_path) -> None:
    case = stability_case(tmp_path, intervals=(OnlyResearchTemporalSlice(0, 2), OnlyResearchTemporalSlice(2, 4)))
    source = case[8].load_verified(case[6].statistics_fingerprint)
    rows = (_row(0, "0.000000000001"), _row(1, "0"), _row(1, "0"), _row(2, "0"))
    summary = only_compute_research_temporal_stability(_source_with(source, rows), case[11])
    assert tuple(item.mean.decimal_value for item in summary.slices) == (
        Decimal("0.000000000000"),
        Decimal("0.000000000000"),
    )
    assert summary.positive_mean_slice_count.integer_value == 0
    assert summary.zero_mean_slice_count.integer_value == 2
    assert summary.stddev_of_slice_means.decimal_value == Decimal("0.000000000000")


def test_identity_source_result_layering_and_exact_source_validation(tmp_path) -> None:
    case = stability_case(tmp_path)
    plan = case[11]
    changes = (
        replace(plan, dataset_snapshot_fingerprint="1" * 64),
        replace(plan, subject_candidate_fingerprint="2" * 64),
        replace(plan, subject=replace(plan.subject, output_name="other")),
        replace(plan, source_statistics_fingerprint="3" * 64),
        replace(plan, definition=OnlyResearchTemporalStabilityDefinition(OnlyResearchStatisticsMethod.RANK_IC)),
        replace(plan, intervals=(OnlyResearchTemporalSlice(0, 3), OnlyResearchTemporalSlice(3, 4))),
        replace(
            plan,
            intervals=(
                *plan.intervals,
                OnlyResearchTemporalSlice(plan.intervals[-1].end_ts_event_ns, 1767577000000000000),
            ),
        ),
    )
    assert all(item.statistics_fingerprint != plan.statistics_fingerprint for item in changes)
    assert (
        replace(plan, source_statistics_result_fingerprint="4" * 64).statistics_fingerprint
        == plan.statistics_fingerprint
    )
    source = case[8].load_verified(case[6].statistics_fingerprint)
    for mutation in (
        replace(plan, dataset_snapshot_fingerprint="1" * 64),
        replace(plan, source_statistics_result_fingerprint="4" * 64),
        replace(plan, subject=replace(plan.subject, output_name="other")),
    ):
        with pytest.raises(OnlyResearchEvaluationError):
            only_compute_research_temporal_stability(source, mutation)


def test_decimal_poisoning_rank_ic_execute_and_reuse_are_deterministic(tmp_path) -> None:
    case = stability_case(tmp_path, OnlyResearchStatisticsMethod.RANK_IC)
    source = case[8].load_verified(case[11].source_statistics_fingerprint)
    rows = (_row(0, "0.1"), _row(1, "0.2"), _row(2, "0.3"), _row(3, "0.4"))
    source = _source_with(source, rows)
    expected = only_compute_research_temporal_stability(source, case[11])
    with localcontext() as context:
        context.prec = 4
        context.rounding = ROUND_DOWN
        context.Emin = -5
        context.Emax = 5
        context.clamp = 1
        context.traps[Inexact] = True
        context.flags[Rounded] = True
        assert only_compute_research_temporal_stability(source, case[11]) == expected
    first = case[13].execute(case[11])
    second = case[13].execute(case[11])
    assert first.disposition is OnlyResearchStatisticsDisposition.EXECUTED
    assert second.disposition is OnlyResearchStatisticsDisposition.REUSED
    loaded = case[12].load_verified(case[11].statistics_fingerprint)
    assert loaded.summary.source_method is OnlyResearchStatisticsMethod.RANK_IC
    assert loaded.summary.slice_count.metric_id == "research.factor.rank_ic.stability.slice_count@1"
