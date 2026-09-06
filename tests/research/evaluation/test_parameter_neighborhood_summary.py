from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, getcontext, localcontext

import pytest

from onlyalpha.research import (
    OnlyResearchParameterNeighborhoodCandidateBinding,
    OnlyResearchParameterNeighborhoodSummaryDefinition,
    OnlyResearchParameterNeighborhoodSummaryPlan,
    OnlyResearchStatisticsMethod,
    OnlyResearchSummaryKind,
    OnlyResearchSummaryScalarStatus,
    only_compute_research_parameter_neighborhood_summary,
)
from onlyalpha.research.evaluation import ONLY_RESEARCH_SUMMARY_METRICS
from onlyalpha.research.evaluation.errors import OnlyResearchEvaluationError
from tests.research.evaluation.support import (
    coverage_case,
    factor_pair_effect_case,
    stability_case,
    summary_case,
)


def _effect_sources(
    tmp_path,
    count: int = 5,
    source_method: OnlyResearchStatisticsMethod = OnlyResearchStatisticsMethod.IC,
):
    case = summary_case(tmp_path, source_method)
    base = case[11]
    results = []
    bindings = []
    for index in range(count):
        candidate = f"{index + 1:x}" * 64
        plan = replace(base, subject_candidate_fingerprint=candidate)
        case[13].execute(plan)
        result = case[12].load_verified(plan.statistics_fingerprint)
        results.append(result)
        bindings.append(
            OnlyResearchParameterNeighborhoodCandidateBinding(
                candidate,
                {"window": 5 + index, "threshold": Decimal(f"0.{index + 1}")},
                result.manifest.statistics_fingerprint,
                result.manifest.statistics_result_fingerprint,
            )
        )
    source_metric_id = (
        "research.factor.ic.mean@1"
        if source_method is OnlyResearchStatisticsMethod.IC
        else "research.factor.rank_ic.mean@1"
    )
    definition = OnlyResearchParameterNeighborhoodSummaryDefinition(source_metric_id)
    plan = OnlyResearchParameterNeighborhoodSummaryPlan(
        base.dataset_snapshot_fingerprint,
        definition.source_metric_id,
        bindings[0],
        tuple(bindings[1:]),
        definition,
    )
    return case, tuple(results), tuple(bindings), plan


def _with_mean(result, value: Decimal | None):
    status = (
        OnlyResearchSummaryScalarStatus.VALID
        if value is not None
        else OnlyResearchSummaryScalarStatus.NO_VALID_OBSERVATIONS
    )
    if value is not None:
        return replace(
            result,
            summary=replace(result.summary, mean=replace(result.summary.mean, status=status, decimal_value=value)),
        )
    summary = result.summary
    absent = OnlyResearchSummaryScalarStatus.NO_VALID_OBSERVATIONS
    insufficient = OnlyResearchSummaryScalarStatus.INSUFFICIENT_OBSERVATIONS
    return replace(
        result,
        summary=replace(
            summary,
            total_count=replace(summary.total_count, integer_value=0),
            valid_count=replace(summary.valid_count, integer_value=0),
            insufficient_observations_count=replace(summary.insufficient_observations_count, integer_value=0),
            zero_variance_feature_count=replace(summary.zero_variance_feature_count, integer_value=0),
            zero_variance_target_count=replace(summary.zero_variance_target_count, integer_value=0),
            mean=replace(summary.mean, status=absent, decimal_value=None),
            stddev_sample=replace(summary.stddev_sample, status=insufficient, decimal_value=None),
            information_ratio=replace(summary.information_ratio, status=insufficient, decimal_value=None),
            positive_count=replace(summary.positive_count, integer_value=0),
            negative_count=replace(summary.negative_count, integer_value=0),
            zero_count=replace(summary.zero_count, integer_value=0),
            positive_ratio=replace(summary.positive_ratio, status=absent, decimal_value=None),
            negative_ratio=replace(summary.negative_ratio, status=absent, decimal_value=None),
            zero_ratio=replace(summary.zero_ratio, status=absent, decimal_value=None),
        ),
    )


def test_neighborhood_definition_binding_assignment_and_plan_round_trip(tmp_path) -> None:
    _, _, bindings, plan = _effect_sources(tmp_path, 3)
    assert OnlyResearchParameterNeighborhoodSummaryDefinition.from_dict(plan.definition.to_dict()) == plan.definition
    assert OnlyResearchParameterNeighborhoodCandidateBinding.from_dict(bindings[0].to_dict()) == bindings[0]
    assert OnlyResearchParameterNeighborhoodSummaryPlan.from_dict(plan.to_dict()) == plan
    reverse_assignment = OnlyResearchParameterNeighborhoodCandidateBinding(
        bindings[0].candidate_fingerprint,
        {"threshold": Decimal("0.1"), "window": 5},
        bindings[0].source_statistics_fingerprint,
        bindings[0].source_statistics_result_fingerprint,
    )
    assert reverse_assignment.to_dict() == bindings[0].to_dict()


def test_neighborhood_metric_vocabulary_is_exact_and_append_only() -> None:
    metrics = tuple(
        item
        for item in ONLY_RESEARCH_SUMMARY_METRICS
        if item.summary_kind is OnlyResearchSummaryKind.PARAMETER_NEIGHBORHOOD_SUMMARY
    )
    assert len(metrics) == 20
    assert {item.source_method for item in metrics} == {
        OnlyResearchStatisticsMethod.IC,
        OnlyResearchStatisticsMethod.RANK_IC,
    }
    assert {item.field_name for item in metrics} == {
        "focal_value",
        "neighbor_count",
        "valid_neighbor_count",
        "neighbor_no_valid_observations_count",
        "neighbor_mean",
        "neighbor_min",
        "neighbor_max",
        "neighbor_stddev_sample",
        "local_range",
        "focal_minus_neighbor_mean",
    }


def test_rank_ic_neighborhood_uses_exact_rank_metric_namespace(tmp_path) -> None:
    _, results, _, plan = _effect_sources(tmp_path, 2, OnlyResearchStatisticsMethod.RANK_IC)
    summary = only_compute_research_parameter_neighborhood_summary(results[0], results[1:], plan)
    assert summary.focal_value.metric_id == "research.factor.neighborhood.rank_ic.focal_value@1"
    assert summary.neighbor_mean.metric_id == "research.factor.neighborhood.rank_ic.neighbor_mean@1"


@pytest.mark.parametrize("metric", ("research.factor.ic.ir@1", "research.factor.ic.coverage.pair_count_mean@1", "x"))
def test_neighborhood_rejects_unsupported_source_metrics(metric: str) -> None:
    with pytest.raises(ValueError, match="source metric"):
        OnlyResearchParameterNeighborhoodSummaryDefinition(metric)


def test_neighborhood_membership_and_identity_rules(tmp_path) -> None:
    _, _, bindings, plan = _effect_sources(tmp_path, 4)
    with pytest.raises(ValueError, match="focal Candidate"):
        replace(plan, neighbors=(bindings[0],))
    with pytest.raises(ValueError, match="unique"):
        replace(plan, neighbors=(bindings[1], bindings[1]))
    reversed_plan = replace(plan, neighbors=tuple(reversed(plan.neighbors)))
    assert reversed_plan.neighbors == tuple(reversed(plan.neighbors))
    assert reversed_plan.statistics_fingerprint != plan.statistics_fingerprint
    assert (
        replace(plan, focal=replace(plan.focal, assignment={"window": 99})).statistics_fingerprint
        != plan.statistics_fingerprint
    )
    assert (
        replace(
            plan,
            focal=replace(plan.focal, source_statistics_result_fingerprint="f" * 64),
        ).statistics_fingerprint
        == plan.statistics_fingerprint
    )
    assert replace(plan, dataset_snapshot_fingerprint="e" * 64).statistics_fingerprint != plan.statistics_fingerprint


def test_neighborhood_all_valid_golden(tmp_path) -> None:
    _, results, _, plan = _effect_sources(tmp_path)
    focal = _with_mean(results[0], Decimal("0.043000000000"))
    neighbors = tuple(
        _with_mean(result, value)
        for result, value in zip(
            results[1:],
            map(Decimal, ("0.038000000000", "0.041000000000", "0.040000000000", "0.037000000000")),
            strict=True,
        )
    )
    summary = only_compute_research_parameter_neighborhood_summary(focal, neighbors, plan)
    assert summary.focal_value.decimal_value == Decimal("0.043000000000")
    assert summary.neighbor_count.integer_value == 4
    assert summary.valid_neighbor_count.integer_value == 4
    assert summary.neighbor_no_valid_observations_count.integer_value == 0
    assert summary.neighbor_mean.decimal_value == Decimal("0.039000000000")
    assert summary.neighbor_min.decimal_value == Decimal("0.037000000000")
    assert summary.neighbor_max.decimal_value == Decimal("0.041000000000")
    assert summary.neighbor_stddev_sample.decimal_value == Decimal("0.001825741858")
    assert summary.local_range.decimal_value == Decimal("0.004000000000")
    assert summary.focal_minus_neighbor_mean.decimal_value == Decimal("0.004000000000")


def test_neighborhood_difference_uses_published_mean_not_unpublished_intermediate(tmp_path) -> None:
    _, results, _, plan = _effect_sources(tmp_path, 3)
    focal = _with_mean(results[0], Decimal("0.000000000001"))
    neighbors = (
        _with_mean(results[1], Decimal("0.000000000000")),
        _with_mean(results[2], Decimal("0.000000000001")),
    )
    summary = only_compute_research_parameter_neighborhood_summary(focal, neighbors, plan)
    assert summary.neighbor_mean.decimal_value == Decimal("0.000000000000")
    assert summary.focal_minus_neighbor_mean.decimal_value == Decimal("0.000000000001")


def test_neighborhood_empty_one_invalid_mixed_and_zero_dispersion(tmp_path) -> None:
    _, results, bindings, plan = _effect_sources(tmp_path, 4)
    empty = replace(plan, neighbors=())
    summary = only_compute_research_parameter_neighborhood_summary(results[0], (), empty)
    assert summary.neighbor_count.integer_value == summary.valid_neighbor_count.integer_value == 0
    assert summary.neighbor_mean.status is OnlyResearchSummaryScalarStatus.NO_VALID_OBSERVATIONS
    assert summary.neighbor_stddev_sample.status is OnlyResearchSummaryScalarStatus.INSUFFICIENT_OBSERVATIONS

    one_plan = replace(plan, neighbors=(bindings[1],))
    one = only_compute_research_parameter_neighborhood_summary(
        results[0], (_with_mean(results[1], Decimal("0.200000000000")),), one_plan
    )
    assert one.local_range.decimal_value == Decimal("0.000000000000")
    assert one.neighbor_stddev_sample.status is OnlyResearchSummaryScalarStatus.INSUFFICIENT_OBSERVATIONS

    mixed = only_compute_research_parameter_neighborhood_summary(
        _with_mean(results[0], None),
        (
            _with_mean(results[1], Decimal("0.300000000000")),
            _with_mean(results[2], None),
            _with_mean(results[3], Decimal("0.300000000000")),
        ),
        plan,
    )
    assert mixed.valid_neighbor_count.integer_value == 2
    assert mixed.neighbor_no_valid_observations_count.integer_value == 1
    assert mixed.neighbor_mean.decimal_value == Decimal("0.300000000000")
    assert mixed.neighbor_stddev_sample.decimal_value == Decimal("0.000000000000")
    assert mixed.local_range.decimal_value == Decimal("0.000000000000")
    assert mixed.focal_minus_neighbor_mean.status is OnlyResearchSummaryScalarStatus.NO_VALID_OBSERVATIONS


def test_neighborhood_all_invalid_neighbors_are_counted_not_zero_filled(tmp_path) -> None:
    _, results, _, plan = _effect_sources(tmp_path, 3)
    summary = only_compute_research_parameter_neighborhood_summary(
        results[0], tuple(_with_mean(item, None) for item in results[1:]), plan
    )
    assert summary.neighbor_count.integer_value == 2
    assert summary.valid_neighbor_count.integer_value == 0
    assert summary.neighbor_no_valid_observations_count.integer_value == 2
    for scalar in (summary.neighbor_mean, summary.neighbor_min, summary.neighbor_max, summary.local_range):
        assert scalar.status is OnlyResearchSummaryScalarStatus.NO_VALID_OBSERVATIONS
        assert scalar.decimal_value is None


def test_neighborhood_decimal_context_poisoning_is_irrelevant(tmp_path) -> None:
    _, results, _, plan = _effect_sources(tmp_path, 3)
    values = (
        _with_mean(results[1], Decimal("0.123456789012")),
        _with_mean(results[2], Decimal("0.987654321098")),
    )
    expected = only_compute_research_parameter_neighborhood_summary(results[0], values, plan)
    caller = getcontext()
    flags = dict(caller.flags)
    with localcontext() as poisoned:
        poisoned.prec = 3
        poisoned.rounding = "ROUND_UP"
        poisoned.Emin = -9
        poisoned.Emax = 9
        for signal in poisoned.traps:
            poisoned.traps[signal] = False
        actual = only_compute_research_parameter_neighborhood_summary(results[0], values, plan)
    assert actual == expected
    assert dict(caller.flags) == flags


def test_neighborhood_exact_source_binding_failures(tmp_path) -> None:
    _, results, bindings, plan = _effect_sources(tmp_path, 3)
    wrong_candidate_plan = replace(
        plan,
        neighbors=(replace(bindings[1], candidate_fingerprint="a" * 64), bindings[2]),
    )
    with pytest.raises(OnlyResearchEvaluationError, match="CANDIDATE_MISMATCH"):
        only_compute_research_parameter_neighborhood_summary(results[0], results[1:], wrong_candidate_plan)
    wrong_metric = replace(
        plan,
        definition=OnlyResearchParameterNeighborhoodSummaryDefinition("research.factor.rank_ic.mean@1"),
        source_metric_id="research.factor.rank_ic.mean@1",
    )
    with pytest.raises(OnlyResearchEvaluationError, match="SOURCE_METRIC_MISMATCH"):
        only_compute_research_parameter_neighborhood_summary(results[0], results[1:], wrong_metric)
    with pytest.raises(OnlyResearchEvaluationError, match="DATASET_MISMATCH"):
        only_compute_research_parameter_neighborhood_summary(
            results[0], results[1:], replace(plan, dataset_snapshot_fingerprint="d" * 64)
        )


@pytest.mark.parametrize(
    ("name", "factory", "plan_index", "store_index", "executor_index"),
    (
        ("coverage", coverage_case, 11, 12, 13),
        ("stability", stability_case, 11, 12, 13),
        ("pair-effect", factor_pair_effect_case, 13, 14, 15),
    ),
)
def test_neighborhood_rejects_wrong_summary_source_family(
    tmp_path, name, factory, plan_index, store_index, executor_index
) -> None:
    _, _, _, plan = _effect_sources(tmp_path / "effect", 2)
    case = factory(tmp_path / name)
    case[executor_index].execute(case[plan_index])
    wrong = case[store_index].load_verified(case[plan_index].statistics_fingerprint)
    wrong_plan = replace(
        plan,
        focal=replace(
            plan.focal,
            source_statistics_fingerprint=wrong.manifest.statistics_fingerprint,
            source_statistics_result_fingerprint=wrong.manifest.statistics_result_fingerprint,
        ),
        dataset_snapshot_fingerprint=wrong.manifest.dataset_snapshot_fingerprint,
        neighbors=(),
    )
    with pytest.raises(OnlyResearchEvaluationError, match="SOURCE_SCHEMA_UNSUPPORTED"):
        only_compute_research_parameter_neighborhood_summary(wrong, (), wrong_plan)


def test_neighborhood_source_result_identity_does_not_change_logical_identity_but_fails_exact_verification(
    tmp_path,
) -> None:
    _, results, _, plan = _effect_sources(tmp_path, 2)
    changed = replace(plan, focal=replace(plan.focal, source_statistics_result_fingerprint="f" * 64))
    assert changed.statistics_fingerprint == plan.statistics_fingerprint
    with pytest.raises(OnlyResearchEvaluationError, match="SOURCE_IDENTITY_MISMATCH"):
        only_compute_research_parameter_neighborhood_summary(results[0], results[1:], changed)
