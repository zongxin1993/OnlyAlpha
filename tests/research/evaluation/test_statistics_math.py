from __future__ import annotations

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from onlyalpha.research.evaluation import (
    OnlyResearchAlignedObservation,
    OnlyResearchAlignedPair,
    OnlyResearchStatisticsDefinition,
    OnlyResearchStatisticsMethod,
    OnlyResearchStatisticStatus,
    only_compute_research_statistics,
)


def _row(
    feature: list[Decimal],
    target: list[Decimal],
    *,
    method: OnlyResearchStatisticsMethod = OnlyResearchStatisticsMethod.IC,
    minimum: int = 2,
):
    pairs = tuple(
        OnlyResearchAlignedPair(f"{index:04d}.X", left, right)
        for index, (left, right) in enumerate(zip(feature, target, strict=True))
    )
    return only_compute_research_statistics(
        (OnlyResearchAlignedObservation(1, pairs),),
        OnlyResearchStatisticsDefinition(method, minimum),
    )[0]


@given(
    st.lists(st.integers(-10000, 10000), min_size=2, max_size=40, unique=True),
    st.integers(1, 100),
    st.integers(-1000, 1000),
)
def test_ic_positive_and_negative_affine_invariance(values: list[int], scale: int, shift: int) -> None:
    feature = [Decimal(value) for value in values]
    positive = [Decimal(scale * value + shift) for value in values]
    negative = [Decimal(-scale * value + shift) for value in values]
    assert _row(feature, positive).statistic_value == Decimal("1.000000000000")
    assert _row(feature, negative).statistic_value == Decimal("-1.000000000000")


@given(st.lists(st.integers(-10000, 10000), min_size=2, max_size=40, unique=True))
def test_ic_is_unchanged_by_instrument_permutation_shift_and_positive_scale(values: list[int]) -> None:
    feature = [Decimal(value) for value in values]
    target = [Decimal(3 * value * value + value) for value in values]
    baseline = _row(feature, target).statistic_value
    assert _row(list(reversed(feature)), list(reversed(target))).statistic_value == baseline
    assert _row([value + 17 for value in feature], target).statistic_value == baseline
    assert _row([value * 7 for value in feature], target).statistic_value == baseline


def test_ic_statuses_and_minimum_boundary_are_exact() -> None:
    assert _row([Decimal(1)], [Decimal(2)], minimum=2).status is (OnlyResearchStatisticStatus.INSUFFICIENT_OBSERVATIONS)
    assert _row([Decimal(1), Decimal(1)], [Decimal(1), Decimal(2)]).status is (
        OnlyResearchStatisticStatus.ZERO_VARIANCE_FEATURE
    )
    assert _row([Decimal(1), Decimal(2)], [Decimal(1), Decimal(1)]).status is (
        OnlyResearchStatisticStatus.ZERO_VARIANCE_TARGET
    )
    assert _row([Decimal(1), Decimal(2)], [Decimal(2), Decimal(3)]).status is OnlyResearchStatisticStatus.VALID


@given(st.lists(st.integers(-1000, 1000), min_size=2, max_size=40, unique=True))
def test_rank_ic_is_invariant_under_strict_monotonic_transform_and_permutation(values: list[int]) -> None:
    feature = [Decimal(value) for value in values]
    target = [Decimal(value**3) for value in values]
    baseline = _row(feature, target, method=OnlyResearchStatisticsMethod.RANK_IC).statistic_value
    transformed = [value * Decimal(7) + Decimal(19) for value in feature]
    assert _row(transformed, target, method=OnlyResearchStatisticsMethod.RANK_IC).statistic_value == baseline
    assert (
        _row(
            list(reversed(feature)),
            list(reversed(target)),
            method=OnlyResearchStatisticsMethod.RANK_IC,
        ).statistic_value
        == baseline
    )


def test_rank_ic_uses_exact_average_ties_and_zero_variance_status() -> None:
    tied = _row(
        [Decimal(1), Decimal(1), Decimal(3), Decimal(4)],
        [Decimal(10), Decimal(20), Decimal(30), Decimal(40)],
        method=OnlyResearchStatisticsMethod.RANK_IC,
    )
    assert tied.statistic_value == Decimal("0.948683298051")
    constant = _row(
        [Decimal(1), Decimal(1)],
        [Decimal(2), Decimal(3)],
        method=OnlyResearchStatisticsMethod.RANK_IC,
    )
    assert constant.status is OnlyResearchStatisticStatus.ZERO_VARIANCE_FEATURE
