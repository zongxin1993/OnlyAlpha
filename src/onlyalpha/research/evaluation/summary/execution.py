"""Deterministic typed Summary Statistics calculation and orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Protocol

from onlyalpha.calculation import OnlyNumericDefinition, only_decimal_context, only_quantize_decimal

from ..errors import OnlyResearchEvaluationError, OnlyResearchStatisticsResultStoreError
from ..result import (
    OnlyResearchStatisticRow,
    OnlyResearchStatisticsDisposition,
    OnlyResearchStatisticsOutcome,
    OnlyResearchStatisticsResult,
    OnlyResearchStatisticStatus,
)
from .metric import only_research_coverage_metric, only_research_effect_metric, only_research_stability_metric
from .plan import (
    OnlyResearchCoverageSummaryPlan,
    OnlyResearchEffectSummaryPlan,
    OnlyResearchSummaryPlan,
    OnlyResearchTemporalStabilityPlan,
)
from .result import (
    OnlyResearchCoverageSummary,
    OnlyResearchEffectSummary,
    OnlyResearchSummaryStatisticsResult,
    OnlyResearchTemporalSliceEvidence,
    OnlyResearchTemporalSliceValue,
    OnlyResearchTemporalStabilitySummary,
)
from .scalar import OnlyResearchSummaryScalar, OnlyResearchSummaryScalarStatus


@dataclass(frozen=True, slots=True)
class OnlyResearchEffectSummaryExecution:
    plan: OnlyResearchEffectSummaryPlan
    summary: OnlyResearchEffectSummary


@dataclass(frozen=True, slots=True)
class OnlyResearchCoverageSummaryExecution:
    plan: OnlyResearchCoverageSummaryPlan
    summary: OnlyResearchCoverageSummary


@dataclass(frozen=True, slots=True)
class OnlyResearchTemporalStabilityExecution:
    plan: OnlyResearchTemporalStabilityPlan
    summary: OnlyResearchTemporalStabilitySummary


OnlyResearchSummaryExecution = (
    OnlyResearchEffectSummaryExecution | OnlyResearchCoverageSummaryExecution | OnlyResearchTemporalStabilityExecution
)


class _LegacyStatisticsResultStore(Protocol):
    def load_verified(self, statistics_fingerprint: str) -> OnlyResearchStatisticsResult: ...


class _SummaryStatisticsResultStore(Protocol):
    def load_verified(self, statistics_fingerprint: str) -> OnlyResearchSummaryStatisticsResult: ...

    def commit(self, execution: OnlyResearchSummaryExecution) -> OnlyResearchSummaryStatisticsResult: ...


class OnlyResearchEffectSummaryExecutor:
    def __init__(
        self,
        source_statistics_result_store: _LegacyStatisticsResultStore,
        summary_statistics_result_store: _SummaryStatisticsResultStore,
    ) -> None:
        self._source_store = source_statistics_result_store
        self._summary_store = summary_statistics_result_store

    def execute(self, plan: OnlyResearchEffectSummaryPlan) -> OnlyResearchStatisticsOutcome:
        if not isinstance(plan, OnlyResearchEffectSummaryPlan):
            raise OnlyResearchEvaluationError("EFFECT_SUMMARY_PLAN_INVALID", "execute requires an Effect Summary Plan")
        try:
            existing = self._summary_store.load_verified(plan.statistics_fingerprint)
        except OnlyResearchStatisticsResultStoreError as exc:
            if exc.code != "SUMMARY_STATISTICS_RESULT_NOT_FOUND":
                raise
        except Exception as exc:
            raise OnlyResearchEvaluationError("SUMMARY_STATISTICS_RESULT_REUSE_FAILED", str(exc)) from exc
        else:
            return _outcome(plan, existing, OnlyResearchStatisticsDisposition.REUSED)
        source = _load_source(self._source_store, plan)
        summary = only_compute_research_effect_summary(source, plan)
        try:
            committed = self._summary_store.commit(OnlyResearchEffectSummaryExecution(plan, summary))
        except OnlyResearchStatisticsResultStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchEvaluationError("SUMMARY_STATISTICS_RESULT_COMMIT_FAILED", str(exc)) from exc
        return _outcome(plan, committed, OnlyResearchStatisticsDisposition.EXECUTED)


class OnlyResearchCoverageSummaryExecutor:
    def __init__(
        self,
        source_statistics_result_store: _LegacyStatisticsResultStore,
        summary_statistics_result_store: _SummaryStatisticsResultStore,
    ) -> None:
        self._source_store = source_statistics_result_store
        self._summary_store = summary_statistics_result_store

    def execute(self, plan: OnlyResearchCoverageSummaryPlan) -> OnlyResearchStatisticsOutcome:
        if not isinstance(plan, OnlyResearchCoverageSummaryPlan):
            raise OnlyResearchEvaluationError(
                "COVERAGE_SUMMARY_PLAN_INVALID", "execute requires a Coverage Summary Plan"
            )
        try:
            existing = self._summary_store.load_verified(plan.statistics_fingerprint)
        except OnlyResearchStatisticsResultStoreError as exc:
            if exc.code != "SUMMARY_STATISTICS_RESULT_NOT_FOUND":
                raise
        except Exception as exc:
            raise OnlyResearchEvaluationError("SUMMARY_STATISTICS_RESULT_REUSE_FAILED", str(exc)) from exc
        else:
            return _outcome(plan, existing, OnlyResearchStatisticsDisposition.REUSED)
        source = _load_source(self._source_store, plan)
        summary = only_compute_research_coverage_summary(source, plan)
        try:
            committed = self._summary_store.commit(OnlyResearchCoverageSummaryExecution(plan, summary))
        except OnlyResearchStatisticsResultStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchEvaluationError("SUMMARY_STATISTICS_RESULT_COMMIT_FAILED", str(exc)) from exc
        return _outcome(plan, committed, OnlyResearchStatisticsDisposition.EXECUTED)


class OnlyResearchTemporalStabilityExecutor:
    def __init__(
        self,
        source_statistics_result_store: _LegacyStatisticsResultStore,
        summary_statistics_result_store: _SummaryStatisticsResultStore,
    ) -> None:
        self._source_store = source_statistics_result_store
        self._summary_store = summary_statistics_result_store

    def execute(self, plan: OnlyResearchTemporalStabilityPlan) -> OnlyResearchStatisticsOutcome:
        if not isinstance(plan, OnlyResearchTemporalStabilityPlan):
            raise OnlyResearchEvaluationError(
                "TEMPORAL_STABILITY_PLAN_INVALID", "execute requires a Temporal Stability Plan"
            )
        try:
            existing = self._summary_store.load_verified(plan.statistics_fingerprint)
        except OnlyResearchStatisticsResultStoreError as exc:
            if exc.code != "SUMMARY_STATISTICS_RESULT_NOT_FOUND":
                raise
        except Exception as exc:
            raise OnlyResearchEvaluationError("SUMMARY_STATISTICS_RESULT_REUSE_FAILED", str(exc)) from exc
        else:
            return _outcome(plan, existing, OnlyResearchStatisticsDisposition.REUSED)
        source = _load_source(self._source_store, plan)
        summary = only_compute_research_temporal_stability(source, plan)
        try:
            committed = self._summary_store.commit(OnlyResearchTemporalStabilityExecution(plan, summary))
        except OnlyResearchStatisticsResultStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchEvaluationError("SUMMARY_STATISTICS_RESULT_COMMIT_FAILED", str(exc)) from exc
        return _outcome(plan, committed, OnlyResearchStatisticsDisposition.EXECUTED)


def only_compute_research_effect_summary(
    source: OnlyResearchStatisticsResult,
    plan: OnlyResearchEffectSummaryPlan,
) -> OnlyResearchEffectSummary:
    _validate_source(source, plan)
    method = plan.definition.source_method
    values = tuple(
        row.statistic_value
        for row in source.rows
        if row.status is OnlyResearchStatisticStatus.VALID and row.statistic_value is not None
    )
    status_counts = {status: 0 for status in OnlyResearchStatisticStatus}
    for row in source.rows:
        status_counts[row.status] += 1
    positive = sum(value > 0 for value in values)
    negative = sum(value < 0 for value in values)
    zero = sum(value == 0 for value in values)
    count = len(values)
    numeric = plan.definition.numeric

    mean_value: Decimal | None = None
    stddev_value: Decimal | None = None
    ir_value: Decimal | None = None
    positive_ratio: Decimal | None = None
    negative_ratio: Decimal | None = None
    zero_ratio: Decimal | None = None
    zero_variance = False
    if count:
        with localcontext(only_decimal_context(numeric)):
            denominator = Decimal(count)
            mean = sum(values, Decimal(0)) / denominator
            positive_ratio_raw = Decimal(positive) / denominator
            negative_ratio_raw = Decimal(negative) / denominator
            zero_ratio_raw = Decimal(zero) / denominator
            if count >= 2:
                variance = sum(((value - mean) ** 2 for value in values), Decimal(0)) / Decimal(count - 1)
                stddev = variance.sqrt()
                zero_variance = stddev == 0
                if stddev != 0:
                    ir = mean / stddev
                else:
                    ir = None
            else:
                stddev = None
                ir = None
        mean_value = _publish(numeric, mean)
        positive_ratio = _publish(numeric, positive_ratio_raw)
        negative_ratio = _publish(numeric, negative_ratio_raw)
        zero_ratio = _publish(numeric, zero_ratio_raw)
        if stddev is not None:
            stddev_value = _publish(numeric, stddev)
        if ir is not None:
            ir_value = _publish(numeric, ir)

    valid = OnlyResearchSummaryScalarStatus.VALID
    no_values = OnlyResearchSummaryScalarStatus.NO_VALID_OBSERVATIONS
    insufficient = OnlyResearchSummaryScalarStatus.INSUFFICIENT_OBSERVATIONS
    return OnlyResearchEffectSummary(
        source_method=method,
        total_count=_scalar(method, "total_count", valid, integer_value=len(source.rows)),
        valid_count=_scalar(method, "valid_count", valid, integer_value=count),
        insufficient_observations_count=_scalar(
            method,
            "insufficient_observations_count",
            valid,
            integer_value=status_counts[OnlyResearchStatisticStatus.INSUFFICIENT_OBSERVATIONS],
        ),
        zero_variance_feature_count=_scalar(
            method,
            "zero_variance_feature_count",
            valid,
            integer_value=status_counts[OnlyResearchStatisticStatus.ZERO_VARIANCE_FEATURE],
        ),
        zero_variance_target_count=_scalar(
            method,
            "zero_variance_target_count",
            valid,
            integer_value=status_counts[OnlyResearchStatisticStatus.ZERO_VARIANCE_TARGET],
        ),
        mean=_scalar(method, "mean", valid if count else no_values, decimal_value=mean_value),
        stddev_sample=_scalar(
            method, "stddev_sample", valid if count >= 2 else insufficient, decimal_value=stddev_value
        ),
        information_ratio=_scalar(
            method,
            "information_ratio",
            (insufficient if count < 2 else OnlyResearchSummaryScalarStatus.ZERO_VARIANCE if zero_variance else valid),
            decimal_value=ir_value,
        ),
        positive_count=_scalar(method, "positive_count", valid, integer_value=positive),
        negative_count=_scalar(method, "negative_count", valid, integer_value=negative),
        zero_count=_scalar(method, "zero_count", valid, integer_value=zero),
        positive_ratio=_scalar(method, "positive_ratio", valid if count else no_values, decimal_value=positive_ratio),
        negative_ratio=_scalar(method, "negative_ratio", valid if count else no_values, decimal_value=negative_ratio),
        zero_ratio=_scalar(method, "zero_ratio", valid if count else no_values, decimal_value=zero_ratio),
    )


def only_compute_research_coverage_summary(
    source: OnlyResearchStatisticsResult,
    plan: OnlyResearchCoverageSummaryPlan,
) -> OnlyResearchCoverageSummary:
    _validate_source(source, plan)
    method = plan.definition.source_method
    total = len(source.rows)
    status_counts = {status: 0 for status in OnlyResearchStatisticStatus}
    pair_counts: list[int] = []
    for row in source.rows:
        status_counts[row.status] += 1
        pair_counts.append(row.sample_count)
    valid_count = status_counts[OnlyResearchStatisticStatus.VALID]
    pair_total = sum(pair_counts)
    ratio: Decimal | None = None
    pair_mean: Decimal | None = None
    if total:
        with localcontext(only_decimal_context(plan.definition.numeric)):
            denominator = Decimal(total)
            ratio_raw = Decimal(valid_count) / denominator
            pair_mean_raw = Decimal(pair_total) / denominator
        ratio = _publish(plan.definition.numeric, ratio_raw)
        pair_mean = _publish(plan.definition.numeric, pair_mean_raw)
    valid = OnlyResearchSummaryScalarStatus.VALID
    absent = OnlyResearchSummaryScalarStatus.NO_VALID_OBSERVATIONS
    observed_status = valid if total else absent
    return OnlyResearchCoverageSummary(
        source_method=method,
        total_timestamp_count=_coverage_scalar(method, "total_timestamp_count", valid, integer_value=total),
        valid_timestamp_count=_coverage_scalar(method, "valid_timestamp_count", valid, integer_value=valid_count),
        valid_timestamp_ratio=_coverage_scalar(method, "valid_timestamp_ratio", observed_status, decimal_value=ratio),
        insufficient_timestamp_count=_coverage_scalar(
            method,
            "insufficient_timestamp_count",
            valid,
            integer_value=status_counts[OnlyResearchStatisticStatus.INSUFFICIENT_OBSERVATIONS],
        ),
        zero_variance_feature_count=_coverage_scalar(
            method,
            "zero_variance_feature_count",
            valid,
            integer_value=status_counts[OnlyResearchStatisticStatus.ZERO_VARIANCE_FEATURE],
        ),
        zero_variance_target_count=_coverage_scalar(
            method,
            "zero_variance_target_count",
            valid,
            integer_value=status_counts[OnlyResearchStatisticStatus.ZERO_VARIANCE_TARGET],
        ),
        pair_count_total=_coverage_scalar(method, "pair_count_total", valid, integer_value=pair_total),
        pair_count_mean=_coverage_scalar(method, "pair_count_mean", observed_status, decimal_value=pair_mean),
        pair_count_min=_coverage_scalar(
            method,
            "pair_count_min",
            observed_status,
            integer_value=min(pair_counts) if pair_counts else None,
        ),
        pair_count_max=_coverage_scalar(
            method,
            "pair_count_max",
            observed_status,
            integer_value=max(pair_counts) if pair_counts else None,
        ),
    )


def only_compute_research_temporal_stability(
    source: OnlyResearchStatisticsResult,
    plan: OnlyResearchTemporalStabilityPlan,
) -> OnlyResearchTemporalStabilitySummary:
    _validate_source(source, plan)
    slices = tuple(
        _compute_temporal_slice(
            tuple(
                row for row in source.rows if interval.start_ts_event_ns <= row.ts_event_ns < interval.end_ts_event_ns
            ),
            interval.start_ts_event_ns,
            interval.end_ts_event_ns,
            plan.definition.numeric,
        )
        for interval in plan.intervals
    )
    means = tuple(
        item.mean.decimal_value
        for item in slices
        if item.mean.status is OnlyResearchSummaryScalarStatus.VALID and item.mean.decimal_value is not None
    )
    positive = sum(value > 0 for value in means)
    negative = sum(value < 0 for value in means)
    zero = sum(value == 0 for value in means)
    count = len(means)
    positive_ratio: Decimal | None = None
    negative_ratio: Decimal | None = None
    zero_ratio: Decimal | None = None
    stddev: Decimal | None = None
    if count:
        with localcontext(only_decimal_context(plan.definition.numeric)):
            denominator = Decimal(count)
            positive_ratio_raw = Decimal(positive) / denominator
            negative_ratio_raw = Decimal(negative) / denominator
            zero_ratio_raw = Decimal(zero) / denominator
            if count >= 2:
                mean_of_means = sum(means, Decimal(0)) / denominator
                variance = sum(((value - mean_of_means) ** 2 for value in means), Decimal(0)) / Decimal(count - 1)
                stddev_raw = variance.sqrt()
            else:
                stddev_raw = None
        positive_ratio = _publish(plan.definition.numeric, positive_ratio_raw)
        negative_ratio = _publish(plan.definition.numeric, negative_ratio_raw)
        zero_ratio = _publish(plan.definition.numeric, zero_ratio_raw)
        if stddev_raw is not None:
            stddev = _publish(plan.definition.numeric, stddev_raw)
    valid = OnlyResearchSummaryScalarStatus.VALID
    absent = OnlyResearchSummaryScalarStatus.NO_VALID_OBSERVATIONS
    insufficient = OnlyResearchSummaryScalarStatus.INSUFFICIENT_OBSERVATIONS
    method = plan.definition.source_method
    return OnlyResearchTemporalStabilitySummary(
        source_method=method,
        slices=slices,
        slice_count=_stability_scalar(method, "slice_count", valid, integer_value=len(slices)),
        valid_slice_count=_stability_scalar(method, "valid_slice_count", valid, integer_value=count),
        positive_mean_slice_count=_stability_scalar(method, "positive_mean_slice_count", valid, integer_value=positive),
        negative_mean_slice_count=_stability_scalar(method, "negative_mean_slice_count", valid, integer_value=negative),
        zero_mean_slice_count=_stability_scalar(method, "zero_mean_slice_count", valid, integer_value=zero),
        positive_mean_slice_ratio=_stability_scalar(
            method, "positive_mean_slice_ratio", valid if count else absent, decimal_value=positive_ratio
        ),
        negative_mean_slice_ratio=_stability_scalar(
            method, "negative_mean_slice_ratio", valid if count else absent, decimal_value=negative_ratio
        ),
        zero_mean_slice_ratio=_stability_scalar(
            method, "zero_mean_slice_ratio", valid if count else absent, decimal_value=zero_ratio
        ),
        min_slice_mean=_stability_scalar(
            method, "min_slice_mean", valid if count else absent, decimal_value=min(means) if means else None
        ),
        max_slice_mean=_stability_scalar(
            method, "max_slice_mean", valid if count else absent, decimal_value=max(means) if means else None
        ),
        stddev_of_slice_means=_stability_scalar(
            method,
            "stddev_of_slice_means",
            valid if count >= 2 else insufficient,
            decimal_value=stddev,
        ),
    )


def _compute_temporal_slice(
    rows: tuple[OnlyResearchStatisticRow, ...],
    start: int,
    end: int,
    numeric: OnlyNumericDefinition,
) -> OnlyResearchTemporalSliceEvidence:
    values = tuple(
        row.statistic_value
        for row in rows
        if row.status is OnlyResearchStatisticStatus.VALID and row.statistic_value is not None
    )
    count = len(values)
    total = len(rows)
    mean_value: Decimal | None = None
    stddev_value: Decimal | None = None
    ir_value: Decimal | None = None
    ratio_value: Decimal | None = None
    exact_zero_variance = False
    if count:
        with localcontext(only_decimal_context(numeric)):
            mean = sum(values, Decimal(0)) / Decimal(count)
            if count >= 2:
                variance = sum(((value - mean) ** 2 for value in values), Decimal(0)) / Decimal(count - 1)
                stddev = variance.sqrt()
                exact_zero_variance = stddev == 0
                ir = None if exact_zero_variance else mean / stddev
            else:
                stddev = None
                ir = None
        mean_value = _publish(numeric, mean)
        if stddev is not None:
            stddev_value = _publish(numeric, stddev)
        if ir is not None:
            ir_value = _publish(numeric, ir)
    if total:
        with localcontext(only_decimal_context(numeric)):
            ratio_raw = Decimal(count) / Decimal(total)
        ratio_value = _publish(numeric, ratio_raw)
    valid = OnlyResearchSummaryScalarStatus.VALID
    absent = OnlyResearchSummaryScalarStatus.NO_VALID_OBSERVATIONS
    insufficient = OnlyResearchSummaryScalarStatus.INSUFFICIENT_OBSERVATIONS
    return OnlyResearchTemporalSliceEvidence(
        start,
        end,
        total,
        count,
        OnlyResearchTemporalSliceValue(valid if count else absent, mean_value),
        OnlyResearchTemporalSliceValue(valid if count >= 2 else insufficient, stddev_value),
        OnlyResearchTemporalSliceValue(
            insufficient
            if count < 2
            else OnlyResearchSummaryScalarStatus.ZERO_VARIANCE
            if exact_zero_variance
            else valid,
            ir_value,
        ),
        OnlyResearchTemporalSliceValue(valid if total else absent, ratio_value),
    )


def _scalar(
    method: object,
    field_name: str,
    status: OnlyResearchSummaryScalarStatus,
    *,
    integer_value: int | None = None,
    decimal_value: Decimal | None = None,
) -> OnlyResearchSummaryScalar:
    from ..definition import OnlyResearchStatisticsMethod

    if not isinstance(method, OnlyResearchStatisticsMethod):  # pragma: no cover - guarded by Definition
        raise ValueError("Effect Summary source method is invalid")
    descriptor = only_research_effect_metric(method, field_name)
    return OnlyResearchSummaryScalar(
        descriptor.metric_id,
        descriptor.value_kind,
        status,
        integer_value,
        decimal_value,
    )


def _coverage_scalar(
    method: object,
    field_name: str,
    status: OnlyResearchSummaryScalarStatus,
    *,
    integer_value: int | None = None,
    decimal_value: Decimal | None = None,
) -> OnlyResearchSummaryScalar:
    from ..definition import OnlyResearchStatisticsMethod

    if not isinstance(method, OnlyResearchStatisticsMethod):  # pragma: no cover - guarded by Definition
        raise ValueError("Coverage Summary source method is invalid")
    descriptor = only_research_coverage_metric(method, field_name)
    return OnlyResearchSummaryScalar(
        descriptor.metric_id,
        descriptor.value_kind,
        status,
        integer_value,
        decimal_value,
    )


def _stability_scalar(
    method: object,
    field_name: str,
    status: OnlyResearchSummaryScalarStatus,
    *,
    integer_value: int | None = None,
    decimal_value: Decimal | None = None,
) -> OnlyResearchSummaryScalar:
    from ..definition import OnlyResearchStatisticsMethod

    if not isinstance(method, OnlyResearchStatisticsMethod):  # pragma: no cover - guarded by Definition
        raise ValueError("Temporal Stability source method is invalid")
    descriptor = only_research_stability_metric(method, field_name)
    return OnlyResearchSummaryScalar(
        descriptor.metric_id,
        descriptor.value_kind,
        status,
        integer_value,
        decimal_value,
    )


def _publish(numeric: OnlyNumericDefinition, value: Decimal) -> Decimal:
    published = only_quantize_decimal(numeric, value)
    return published.copy_abs() if published.is_zero() else published


def _load_source(
    store: _LegacyStatisticsResultStore,
    plan: OnlyResearchSummaryPlan,
) -> OnlyResearchStatisticsResult:
    try:
        source = store.load_verified(plan.source_statistics_fingerprint)
    except OnlyResearchStatisticsResultStoreError as exc:
        raise OnlyResearchEvaluationError(_source_error_prefix(plan) + "_SOURCE_INVALID", exc.code) from exc
    except Exception as exc:
        raise OnlyResearchEvaluationError(_source_error_prefix(plan) + "_SOURCE_INVALID", str(exc)) from exc
    _validate_source(source, plan)
    return source


def _validate_source(source: OnlyResearchStatisticsResult, plan: OnlyResearchSummaryPlan) -> None:
    prefix = _source_error_prefix(plan)
    if not isinstance(source, OnlyResearchStatisticsResult):
        raise OnlyResearchEvaluationError(prefix + "_SOURCE_SCHEMA_UNSUPPORTED", "legacy V1 required")
    manifest = source.manifest
    if manifest.statistics_fingerprint != plan.source_statistics_fingerprint:
        raise OnlyResearchEvaluationError(prefix + "_SOURCE_IDENTITY_MISMATCH", "logical identity")
    if manifest.statistics_result_fingerprint != plan.source_statistics_result_fingerprint:
        raise OnlyResearchEvaluationError(prefix + "_SOURCE_IDENTITY_MISMATCH", "result identity")
    if manifest.plan.definition.method is not plan.definition.source_method:
        raise OnlyResearchEvaluationError(prefix + "_SOURCE_METHOD_MISMATCH", "source method")
    if manifest.dataset_snapshot_fingerprint != plan.dataset_snapshot_fingerprint:
        raise OnlyResearchEvaluationError(prefix + "_DATASET_MISMATCH", "source Dataset")
    if manifest.plan.feature != plan.subject:
        raise OnlyResearchEvaluationError(prefix + "_SUBJECT_MISMATCH", "source Factor series")


def _source_error_prefix(plan: OnlyResearchSummaryPlan) -> str:
    if isinstance(plan, OnlyResearchEffectSummaryPlan):
        return "EFFECT_SUMMARY"
    if isinstance(plan, OnlyResearchCoverageSummaryPlan):
        return "COVERAGE_SUMMARY"
    if isinstance(plan, OnlyResearchTemporalStabilityPlan):
        return "TEMPORAL_STABILITY"
    raise OnlyResearchEvaluationError("SUMMARY_STATISTICS_PLAN_INVALID", "unsupported Summary Plan")


def _outcome(
    plan: OnlyResearchSummaryPlan,
    result: OnlyResearchSummaryStatisticsResult,
    disposition: OnlyResearchStatisticsDisposition,
) -> OnlyResearchStatisticsOutcome:
    if result.manifest.statistics_fingerprint != plan.statistics_fingerprint or result.manifest.plan != plan:
        raise OnlyResearchEvaluationError("SUMMARY_STATISTICS_RESULT_INVALID", "Result does not match Plan")
    return OnlyResearchStatisticsOutcome(
        disposition,
        result.manifest.statistics_fingerprint,
        result.manifest.statistics_result_fingerprint,
    )


__all__ = [
    "OnlyResearchCoverageSummaryExecution",
    "OnlyResearchCoverageSummaryExecutor",
    "OnlyResearchEffectSummaryExecution",
    "OnlyResearchEffectSummaryExecutor",
    "OnlyResearchSummaryExecution",
    "OnlyResearchTemporalStabilityExecution",
    "OnlyResearchTemporalStabilityExecutor",
    "only_compute_research_coverage_summary",
    "only_compute_research_effect_summary",
    "only_compute_research_temporal_stability",
]
