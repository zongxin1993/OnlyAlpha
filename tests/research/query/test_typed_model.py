from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from onlyalpha.research.query import (
    OnlyResearchCoverageSummaryProjection,
    OnlyResearchEffectSummaryProjection,
    OnlyResearchFactorPairEffectSummaryProjection,
    OnlyResearchParameterNeighborhoodSummaryProjection,
    OnlyResearchQueryError,
    OnlyResearchSeriesReference,
    OnlyResearchTemporalSliceProjection,
    OnlyResearchTemporalSliceValueProjection,
    OnlyResearchTemporalStabilitySummaryProjection,
    OnlyResearchTypedCandidateBinding,
    OnlyResearchTypedFactorOperand,
    OnlyResearchTypedScalar,
    OnlyResearchTypedScalarStatus,
    OnlyResearchTypedScalarValueKind,
    OnlyResearchTypedStatisticsDependency,
    OnlyResearchTypedStatisticSeriesQuery,
    OnlyResearchTypedSummaryKind,
)

SHA = "a" * 64


def _integer_scalar(metric_id: str) -> OnlyResearchTypedScalar:
    return OnlyResearchTypedScalar(
        metric_id,
        OnlyResearchTypedScalarValueKind.INTEGER,
        OnlyResearchTypedScalarStatus.VALID,
        integer_value=1,
    )


def _decimal_scalar(metric_id: str) -> OnlyResearchTypedScalar:
    return OnlyResearchTypedScalar(
        metric_id,
        OnlyResearchTypedScalarValueKind.DECIMAL,
        OnlyResearchTypedScalarStatus.VALID,
        decimal_value=Decimal("0.1"),
    )


def _candidate_metadata() -> dict[str, object]:
    return {
        "research_result_fingerprint": SHA,
        "statistics_fingerprint": "b" * 64,
        "subject_candidate_fingerprint": "c" * 64,
        "subject": OnlyResearchSeriesReference("d" * 64, "e" * 64, "factor"),
        "source": OnlyResearchTypedStatisticsDependency("f" * 64, "1" * 64),
        "source_method": "IC",
    }


@pytest.mark.parametrize(
    "status",
    (
        OnlyResearchTypedScalarStatus.NO_VALID_OBSERVATIONS,
        OnlyResearchTypedScalarStatus.INSUFFICIENT_OBSERVATIONS,
        OnlyResearchTypedScalarStatus.ZERO_VARIANCE,
        OnlyResearchTypedScalarStatus.NOT_APPLICABLE,
    ),
)
def test_non_valid_typed_scalars_preserve_status_and_forbid_numeric_defaults(
    status: OnlyResearchTypedScalarStatus,
) -> None:
    scalar = OnlyResearchTypedScalar(
        "research.test.metric@1",
        OnlyResearchTypedScalarValueKind.DECIMAL,
        status,
    )
    assert scalar.status is status
    assert scalar.integer_value is None
    assert scalar.decimal_value is None
    with pytest.raises(ValueError, match="must not carry"):
        replace(scalar, decimal_value=Decimal("0"))


def test_typed_scalars_keep_exact_decimal_and_integer_types() -> None:
    exact_decimal = Decimal("0.123456789012")
    decimal_scalar = OnlyResearchTypedScalar(
        "research.test.decimal@1",
        OnlyResearchTypedScalarValueKind.DECIMAL,
        OnlyResearchTypedScalarStatus.VALID,
        decimal_value=exact_decimal,
    )
    integer_scalar = OnlyResearchTypedScalar(
        "research.test.integer@1",
        OnlyResearchTypedScalarValueKind.INTEGER,
        OnlyResearchTypedScalarStatus.VALID,
        integer_value=9007199254740993,
    )
    assert type(decimal_scalar.decimal_value) is Decimal
    assert decimal_scalar.decimal_value == exact_decimal
    assert type(integer_scalar.integer_value) is int
    assert integer_scalar.integer_value == 9007199254740993


def test_typed_series_query_reuses_exact_range_cursor_and_limit_validation() -> None:
    identity = "a" * 64
    statistics = "b" * 64
    with pytest.raises(OnlyResearchQueryError):
        OnlyResearchTypedStatisticSeriesQuery(identity, statistics, from_ts_event_ns=2, to_ts_event_ns=2)
    with pytest.raises(OnlyResearchQueryError):
        OnlyResearchTypedStatisticSeriesQuery(identity, statistics, limit=0)
    with pytest.raises(OnlyResearchQueryError):
        OnlyResearchTypedStatisticSeriesQuery(identity, statistics, after_ts_event_ns=True)


def test_effect_and_coverage_projections_self_validate_identity_type_and_kind() -> None:
    effect = OnlyResearchEffectSummaryProjection(
        **_candidate_metadata(),
        total_count=_integer_scalar("research.factor.ic.total_count@1"),
        valid_count=_integer_scalar("research.factor.ic.valid_count@1"),
        insufficient_observations_count=_integer_scalar("research.factor.ic.insufficient_observations_count@1"),
        zero_variance_feature_count=_integer_scalar("research.factor.ic.zero_variance_feature_count@1"),
        zero_variance_target_count=_integer_scalar("research.factor.ic.zero_variance_target_count@1"),
        mean=_decimal_scalar("research.factor.ic.mean@1"),
        stddev_sample=_decimal_scalar("research.factor.ic.stddev_sample@1"),
        information_ratio=_decimal_scalar("research.factor.ic.ir@1"),
        positive_count=_integer_scalar("research.factor.ic.positive_count@1"),
        negative_count=_integer_scalar("research.factor.ic.negative_count@1"),
        zero_count=_integer_scalar("research.factor.ic.zero_count@1"),
        positive_ratio=_decimal_scalar("research.factor.ic.positive_ratio@1"),
        negative_ratio=_decimal_scalar("research.factor.ic.negative_ratio@1"),
        zero_ratio=_decimal_scalar("research.factor.ic.zero_ratio@1"),
    )
    coverage = OnlyResearchCoverageSummaryProjection(
        **_candidate_metadata(),
        total_timestamp_count=_integer_scalar("research.factor.ic.coverage.total_timestamp_count@1"),
        valid_timestamp_count=_integer_scalar("research.factor.ic.coverage.valid_timestamp_count@1"),
        valid_timestamp_ratio=_decimal_scalar("research.factor.ic.coverage.valid_timestamp_ratio@1"),
        insufficient_timestamp_count=_integer_scalar("research.factor.ic.coverage.insufficient_timestamp_count@1"),
        zero_variance_feature_count=_integer_scalar("research.factor.ic.coverage.zero_variance_feature_count@1"),
        zero_variance_target_count=_integer_scalar("research.factor.ic.coverage.zero_variance_target_count@1"),
        pair_count_total=_integer_scalar("research.factor.ic.coverage.pair_count_total@1"),
        pair_count_mean=_decimal_scalar("research.factor.ic.coverage.pair_count_mean@1"),
        pair_count_min=_integer_scalar("research.factor.ic.coverage.pair_count_min@1"),
        pair_count_max=_integer_scalar("research.factor.ic.coverage.pair_count_max@1"),
    )
    with pytest.raises((ValueError, OnlyResearchQueryError)):
        replace(effect, research_result_fingerprint="A" * 64)
    with pytest.raises(ValueError):
        replace(effect, mean=object())
    with pytest.raises(ValueError, match="scalar linkage"):
        replace(effect, mean=effect.stddev_sample)
    with pytest.raises(ValueError, match="scalar linkage"):
        replace(effect, mean=_integer_scalar("research.factor.ic.mean@1"))
    with pytest.raises(ValueError):
        replace(coverage, summary_kind=OnlyResearchTypedSummaryKind.EFFECT_SUMMARY)
    with pytest.raises(ValueError):
        replace(coverage, subject=object())


def test_stability_projection_requires_typed_ordered_non_overlapping_slices() -> None:
    value = OnlyResearchTemporalSliceValueProjection(OnlyResearchTypedScalarStatus.VALID, Decimal("0.1"))
    first = OnlyResearchTemporalSliceProjection(1, 3, 1, 1, value, value, value, value)
    second = OnlyResearchTemporalSliceProjection(3, 5, 1, 1, value, value, value, value)
    stability = OnlyResearchTemporalStabilitySummaryProjection(
        **_candidate_metadata(),
        slices=(first, second),
        slice_count=_integer_scalar("research.factor.ic.stability.slice_count@1"),
        valid_slice_count=_integer_scalar("research.factor.ic.stability.valid_slice_count@1"),
        positive_mean_slice_count=_integer_scalar("research.factor.ic.stability.positive_mean_slice_count@1"),
        negative_mean_slice_count=_integer_scalar("research.factor.ic.stability.negative_mean_slice_count@1"),
        zero_mean_slice_count=_integer_scalar("research.factor.ic.stability.zero_mean_slice_count@1"),
        positive_mean_slice_ratio=_decimal_scalar("research.factor.ic.stability.positive_mean_slice_ratio@1"),
        negative_mean_slice_ratio=_decimal_scalar("research.factor.ic.stability.negative_mean_slice_ratio@1"),
        zero_mean_slice_ratio=_decimal_scalar("research.factor.ic.stability.zero_mean_slice_ratio@1"),
        min_slice_mean=_decimal_scalar("research.factor.ic.stability.min_slice_mean@1"),
        max_slice_mean=_decimal_scalar("research.factor.ic.stability.max_slice_mean@1"),
        stddev_of_slice_means=_decimal_scalar("research.factor.ic.stability.stddev_of_slice_means@1"),
    )
    with pytest.raises(ValueError):
        replace(stability, slices=[first])  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        replace(stability, slices=(second, first))
    with pytest.raises(ValueError):
        replace(stability, slices=(first, replace(second, start_ts_event_ns=2)))
    with pytest.raises(ValueError):
        replace(stability, summary_kind=OnlyResearchTypedSummaryKind.COVERAGE_SUMMARY)


def test_pair_and_neighborhood_projections_self_validate_typed_bindings() -> None:
    dependency = OnlyResearchTypedStatisticsDependency("f" * 64, "1" * 64)
    operand = OnlyResearchTypedFactorOperand("c" * 64, "d" * 64, "e" * 64, "factor")
    pair = OnlyResearchFactorPairEffectSummaryProjection(
        SHA,
        "b" * 64,
        operand,
        replace(operand, candidate_fingerprint="2" * 64),
        dependency,
        "FACTOR_CORRELATION",
        _decimal_scalar("research.factor_pair.correlation.mean@1"),
        _decimal_scalar("research.factor_pair.correlation.stddev_sample@1"),
    )
    binding = OnlyResearchTypedCandidateBinding("c" * 64, (("window", 5),), dependency)
    neighborhood = OnlyResearchParameterNeighborhoodSummaryProjection(
        SHA,
        "b" * 64,
        "research.factor.ic.mean@1",
        binding,
        (replace(binding, candidate_fingerprint="2" * 64),),
        _decimal_scalar("research.factor.neighborhood.ic.focal_value@1"),
        _integer_scalar("research.factor.neighborhood.ic.neighbor_count@1"),
        _integer_scalar("research.factor.neighborhood.ic.valid_neighbor_count@1"),
        _integer_scalar("research.factor.neighborhood.ic.neighbor_no_valid_observations_count@1"),
        _decimal_scalar("research.factor.neighborhood.ic.neighbor_mean@1"),
        _decimal_scalar("research.factor.neighborhood.ic.neighbor_min@1"),
        _decimal_scalar("research.factor.neighborhood.ic.neighbor_max@1"),
        _decimal_scalar("research.factor.neighborhood.ic.neighbor_stddev_sample@1"),
        _decimal_scalar("research.factor.neighborhood.ic.local_range@1"),
        _decimal_scalar("research.factor.neighborhood.ic.focal_minus_neighbor_mean@1"),
    )
    with pytest.raises(ValueError):
        replace(pair, first_operand=object())
    with pytest.raises(ValueError):
        replace(pair, source_method="IC")
    with pytest.raises(ValueError):
        replace(neighborhood, focal=object())
    with pytest.raises(ValueError):
        replace(neighborhood, neighbors=[binding])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="source metric"):
        replace(neighborhood, source_metric_id="research.factor.ic.ir@1")
    with pytest.raises(ValueError, match="Candidate bindings"):
        replace(neighborhood, neighbors=(binding,))
    with pytest.raises(ValueError, match="Candidate bindings"):
        replace(neighborhood, neighbors=(neighborhood.neighbors[0], neighborhood.neighbors[0]))
    assert neighborhood.neighbors[0].candidate_fingerprint == "2" * 64


@pytest.mark.parametrize(
    "assignment",
    (
        (("window", 1), ("alpha", 2)),
        (("window", 1), ("window", 2)),
        (("window", 1), ("window", "two")),
        (("bad name", 1),),
        (("value", 1.5),),
        (("value", []),),
        (("value", {}),),
        (("value", Decimal("NaN")),),
        (("value", Decimal("Infinity")),),
        (("value", object()),),
    ),
)
def test_candidate_binding_rejects_noncanonical_or_unsupported_assignments(
    assignment: tuple[tuple[str, object], ...],
) -> None:
    dependency = OnlyResearchTypedStatisticsDependency("f" * 64, "1" * 64)
    with pytest.raises(ValueError):
        OnlyResearchTypedCandidateBinding("c" * 64, assignment, dependency)


def test_candidate_binding_accepts_exact_canonical_scalar_vocabulary() -> None:
    dependency = OnlyResearchTypedStatisticsDependency("f" * 64, "1" * 64)
    assignment = (
        ("boolean", True),
        ("decimal", Decimal("1.25")),
        ("integer", 3),
        ("null", None),
        ("string", "value"),
    )
    assert OnlyResearchTypedCandidateBinding("c" * 64, assignment, dependency).assignment == assignment
