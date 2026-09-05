from dataclasses import replace
from decimal import Decimal

import pytest

from onlyalpha.research import (
    OnlyResearchEffectSummaryDefinition,
    OnlyResearchEffectSummaryPlan,
    OnlyResearchFeatureSeriesReference,
    OnlyResearchStatisticsFamily,
    OnlyResearchStatisticsMethod,
    OnlyResearchSummaryMetricDescriptor,
    OnlyResearchSummaryScalar,
    OnlyResearchSummaryScalarStatus,
    OnlyResearchSummaryValueKind,
    only_research_effect_metric,
    only_research_statistics_family,
    only_research_summary_metric,
)
from onlyalpha.research.evaluation import (
    ONLY_RESEARCH_SUMMARY_METRICS,
    only_research_summary_result_content_fingerprint,
)


def _plan() -> OnlyResearchEffectSummaryPlan:
    return OnlyResearchEffectSummaryPlan(
        "a" * 64,
        "b" * 64,
        OnlyResearchFeatureSeriesReference("c" * 64, "d" * 64, "factor_value"),
        "e" * 64,
        "f" * 64,
        OnlyResearchEffectSummaryDefinition(OnlyResearchStatisticsMethod.IC),
    )


def test_effect_definition_and_plan_round_trip_are_exact_and_versioned() -> None:
    definition = _plan().definition
    assert OnlyResearchEffectSummaryDefinition.from_dict(definition.to_dict()) == definition
    assert OnlyResearchEffectSummaryPlan.from_dict(_plan().to_dict()) == _plan()
    assert definition.to_dict()["decimal_execution_policy"] == "onlyalpha.decimal.execution@1"
    for field, value in (
        ("standard_deviation", "POPULATION"),
        ("information_ratio", "ANNUALIZED"),
        ("source_method", "FACTOR_CORRELATION"),
        ("schema_version", 2),
    ):
        payload = definition.to_dict()
        payload[field] = value
        with pytest.raises((TypeError, ValueError)):
            OnlyResearchEffectSummaryDefinition.from_dict(payload)
    with pytest.raises(ValueError):
        replace(
            definition,
            standard_deviation=object(),  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError):
        replace(
            definition,
            information_ratio=object(),  # type: ignore[arg-type]
        )


def test_metric_registry_is_exact_immutable_and_method_typed() -> None:
    ids = tuple(item.metric_id for item in ONLY_RESEARCH_SUMMARY_METRICS)
    assert ids == tuple(sorted(ids))
    assert len(ids) == len(set(ids)) == 28
    assert (
        tuple(OnlyResearchSummaryMetricDescriptor.from_dict(item.to_dict()) for item in ONLY_RESEARCH_SUMMARY_METRICS)
        == ONLY_RESEARCH_SUMMARY_METRICS
    )
    assert only_research_summary_metric("research.factor.ic.ir@1").field_name == "information_ratio"
    assert (
        only_research_summary_metric("research.factor.rank_ic.ir@1").source_method
        is OnlyResearchStatisticsMethod.RANK_IC
    )
    assert (
        only_research_effect_metric(OnlyResearchStatisticsMethod.IC, "total_count").value_kind
        is OnlyResearchSummaryValueKind.INTEGER
    )
    assert (
        only_research_effect_metric(OnlyResearchStatisticsMethod.IC, "mean").value_kind
        is OnlyResearchSummaryValueKind.DECIMAL
    )
    with pytest.raises(ValueError, match="unsupported"):
        only_research_summary_metric("research.factor.ic.mean@2")


def test_statistics_family_dispatch_is_explicit_and_unknown_schema_fails_closed() -> None:
    assert only_research_statistics_family({"schema_version": 1}) is (
        OnlyResearchStatisticsFamily.FEATURE_TARGET_CORRELATION_SERIES_V1
    )
    assert (
        only_research_statistics_family({"schema_version": 1, "domain": "RESEARCH_SUMMARY_STATISTICS"})
        is OnlyResearchStatisticsFamily.SUMMARY_STATISTICS_V1
    )
    with pytest.raises(ValueError, match="unsupported"):
        only_research_statistics_family({"schema_version": 2})


def test_summary_scalar_invariants_and_round_trip() -> None:
    integer_id = "research.factor.ic.total_count@1"
    decimal_id = "research.factor.ic.mean@1"
    zero = OnlyResearchSummaryScalar(
        decimal_id,
        OnlyResearchSummaryValueKind.DECIMAL,
        OnlyResearchSummaryScalarStatus.VALID,
        decimal_value=Decimal("0.000000000000"),
    )
    assert OnlyResearchSummaryScalar.from_dict(zero.to_dict()) == zero
    assert zero.decimal_value == 0
    invalid = OnlyResearchSummaryScalar(
        decimal_id,
        OnlyResearchSummaryValueKind.DECIMAL,
        OnlyResearchSummaryScalarStatus.NO_VALID_OBSERVATIONS,
    )
    assert invalid.decimal_value is None
    bad = (
        (integer_id, OnlyResearchSummaryValueKind.INTEGER, OnlyResearchSummaryScalarStatus.VALID, None, None),
        (integer_id, OnlyResearchSummaryValueKind.INTEGER, OnlyResearchSummaryScalarStatus.VALID, 1, Decimal(1)),
        (integer_id, OnlyResearchSummaryValueKind.INTEGER, OnlyResearchSummaryScalarStatus.VALID, -1, None),
        (decimal_id, OnlyResearchSummaryValueKind.INTEGER, OnlyResearchSummaryScalarStatus.VALID, 1, None),
        (decimal_id, OnlyResearchSummaryValueKind.DECIMAL, OnlyResearchSummaryScalarStatus.VALID, None, Decimal("NaN")),
        (decimal_id, OnlyResearchSummaryValueKind.DECIMAL, OnlyResearchSummaryScalarStatus.VALID, None, Decimal("0.1")),
        (
            decimal_id,
            OnlyResearchSummaryValueKind.DECIMAL,
            OnlyResearchSummaryScalarStatus.VALID,
            None,
            Decimal("-0.000000000000"),
        ),
        (
            decimal_id,
            OnlyResearchSummaryValueKind.DECIMAL,
            OnlyResearchSummaryScalarStatus.ZERO_VARIANCE,
            None,
            Decimal(0),
        ),
    )
    for args in bad:
        with pytest.raises(ValueError):
            OnlyResearchSummaryScalar(*args)


def test_each_semantic_plan_input_changes_logical_identity_but_source_result_does_not() -> None:
    plan = _plan()
    changes = (
        replace(plan, dataset_snapshot_fingerprint="1" * 64),
        replace(plan, subject_candidate_fingerprint="2" * 64),
        replace(plan, subject=replace(plan.subject, output_name="other")),
        replace(plan, source_statistics_fingerprint="3" * 64),
        replace(plan, definition=OnlyResearchEffectSummaryDefinition(OnlyResearchStatisticsMethod.RANK_IC)),
    )
    assert all(item.statistics_fingerprint != plan.statistics_fingerprint for item in changes)
    assert (
        replace(plan, source_statistics_result_fingerprint="4" * 64).statistics_fingerprint
        == plan.statistics_fingerprint
    )


def test_exact_source_result_identity_is_bound_by_result_content_not_logical_identity() -> None:
    plan = _plan()
    payload = {"fixed": "typed"}
    first = only_research_summary_result_content_fingerprint(
        plan.source_statistics_fingerprint, plan.source_statistics_result_fingerprint, payload
    )
    second = only_research_summary_result_content_fingerprint(plan.source_statistics_fingerprint, "1" * 64, payload)
    assert first != second


def test_exact_payload_readers_reject_unknown_fields() -> None:
    payload = _plan().to_dict()
    payload["unknown"] = True
    with pytest.raises(ValueError, match="fields"):
        OnlyResearchEffectSummaryPlan.from_dict(payload)
