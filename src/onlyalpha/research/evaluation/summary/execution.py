"""Deterministic Effect Summary calculation and orchestration."""

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
from .metric import only_research_effect_metric
from .plan import OnlyResearchEffectSummaryPlan
from .result import OnlyResearchEffectSummary, OnlyResearchSummaryStatisticsResult
from .scalar import OnlyResearchSummaryScalar, OnlyResearchSummaryScalarStatus


@dataclass(frozen=True, slots=True)
class OnlyResearchEffectSummaryExecution:
    plan: OnlyResearchEffectSummaryPlan
    summary: OnlyResearchEffectSummary


class _LegacyStatisticsResultStore(Protocol):
    def load_verified(self, statistics_fingerprint: str) -> OnlyResearchStatisticsResult: ...


class _SummaryStatisticsResultStore(Protocol):
    def load_verified(self, statistics_fingerprint: str) -> OnlyResearchSummaryStatisticsResult: ...

    def commit(self, execution: OnlyResearchEffectSummaryExecution) -> OnlyResearchSummaryStatisticsResult: ...


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


def _publish(numeric: OnlyNumericDefinition, value: Decimal) -> Decimal:
    published = only_quantize_decimal(numeric, value)
    return published.copy_abs() if published.is_zero() else published


def _load_source(
    store: _LegacyStatisticsResultStore,
    plan: OnlyResearchEffectSummaryPlan,
) -> OnlyResearchStatisticsResult:
    try:
        source = store.load_verified(plan.source_statistics_fingerprint)
    except OnlyResearchStatisticsResultStoreError as exc:
        raise OnlyResearchEvaluationError("EFFECT_SUMMARY_SOURCE_INVALID", exc.code) from exc
    except Exception as exc:
        raise OnlyResearchEvaluationError("EFFECT_SUMMARY_SOURCE_INVALID", str(exc)) from exc
    _validate_source(source, plan)
    return source


def _validate_source(source: OnlyResearchStatisticsResult, plan: OnlyResearchEffectSummaryPlan) -> None:
    if not isinstance(source, OnlyResearchStatisticsResult):
        raise OnlyResearchEvaluationError("EFFECT_SUMMARY_SOURCE_SCHEMA_UNSUPPORTED", "legacy V1 required")
    manifest = source.manifest
    if manifest.statistics_fingerprint != plan.source_statistics_fingerprint:
        raise OnlyResearchEvaluationError("EFFECT_SUMMARY_SOURCE_IDENTITY_MISMATCH", "logical identity")
    if manifest.statistics_result_fingerprint != plan.source_statistics_result_fingerprint:
        raise OnlyResearchEvaluationError("EFFECT_SUMMARY_SOURCE_IDENTITY_MISMATCH", "result identity")
    if manifest.plan.definition.method is not plan.definition.source_method:
        raise OnlyResearchEvaluationError("EFFECT_SUMMARY_SOURCE_METHOD_MISMATCH", "source method")
    if manifest.dataset_snapshot_fingerprint != plan.dataset_snapshot_fingerprint:
        raise OnlyResearchEvaluationError("EFFECT_SUMMARY_DATASET_MISMATCH", "source Dataset")
    if manifest.plan.feature != plan.subject:
        raise OnlyResearchEvaluationError("EFFECT_SUMMARY_SUBJECT_MISMATCH", "source Factor series")


def _outcome(
    plan: OnlyResearchEffectSummaryPlan,
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
    "OnlyResearchEffectSummaryExecution",
    "OnlyResearchEffectSummaryExecutor",
    "only_compute_research_effect_summary",
]
