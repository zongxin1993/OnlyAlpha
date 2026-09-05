"""Deterministic typed Summary Statistics calculation and orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Protocol

from onlyalpha.calculation import OnlyNumericDefinition, only_decimal_context, only_quantize_decimal

from ..errors import OnlyResearchEvaluationError, OnlyResearchStatisticsResultStoreError
from ..result import (
    OnlyResearchStatisticsDisposition,
    OnlyResearchStatisticsOutcome,
    OnlyResearchStatisticsResult,
    OnlyResearchStatisticStatus,
)
from .metric import only_research_coverage_metric, only_research_effect_metric
from .plan import OnlyResearchCoverageSummaryPlan, OnlyResearchEffectSummaryPlan, OnlyResearchSummaryPlan
from .result import OnlyResearchCoverageSummary, OnlyResearchEffectSummary, OnlyResearchSummaryStatisticsResult
from .scalar import OnlyResearchSummaryScalar, OnlyResearchSummaryScalarStatus


@dataclass(frozen=True, slots=True)
class OnlyResearchEffectSummaryExecution:
    plan: OnlyResearchEffectSummaryPlan
    summary: OnlyResearchEffectSummary


@dataclass(frozen=True, slots=True)
class OnlyResearchCoverageSummaryExecution:
    plan: OnlyResearchCoverageSummaryPlan
    summary: OnlyResearchCoverageSummary


OnlyResearchSummaryExecution = OnlyResearchEffectSummaryExecution | OnlyResearchCoverageSummaryExecution


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
    "only_compute_research_coverage_summary",
    "only_compute_research_effect_summary",
]
