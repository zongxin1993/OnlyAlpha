from __future__ import annotations

from dataclasses import replace
from decimal import ROUND_DOWN, Decimal, Inexact, Rounded, getcontext, localcontext
from typing import cast

import pyarrow as pa  # type: ignore[import-untyped]
import pytest

from onlyalpha.calculation import OnlyNumericDefinition
from onlyalpha.research.calculation.execution import OnlyResearchCalculationNodeOutput
from onlyalpha.research.calculation.result import OnlyResearchCalculationResult
from onlyalpha.research.evaluation import (
    OnlyResearchFactorPairAlignedObservation,
    OnlyResearchFactorPairAlignedPair,
    OnlyResearchFactorPairAlignment,
    OnlyResearchFactorPairOperand,
    OnlyResearchFactorPairStatisticRow,
    OnlyResearchFactorPairStatisticsDefinition,
    OnlyResearchFactorPairStatisticsMethod,
    OnlyResearchFactorPairStatisticsPlan,
    OnlyResearchFactorPairStatisticStatus,
    OnlyResearchFeatureSeriesReference,
    OnlyResearchPairingPolicy,
    OnlyResearchRankTieMethod,
    OnlyResearchUniversePolicy,
    OnlyResearchWeighting,
    only_align_research_factor_pair,
    only_compute_research_factor_pair_statistics,
)
from onlyalpha.research.evaluation.errors import OnlyResearchEvaluationError


def _operand(candidate: str, calculation: str, node: str, output: str = "value") -> OnlyResearchFactorPairOperand:
    return OnlyResearchFactorPairOperand(
        candidate * 64,
        OnlyResearchFeatureSeriesReference(calculation * 64, node * 64, output),
    )


def _plan(swapped: bool = False) -> OnlyResearchFactorPairStatisticsPlan:
    first = _operand("a", "b", "c")
    second = _operand("d", "e", "f")
    if swapped:
        first, second = second, first
    return OnlyResearchFactorPairStatisticsPlan(
        "9" * 64,
        first,
        second,
        OnlyResearchFactorPairStatisticsDefinition(OnlyResearchFactorPairStatisticsMethod.FACTOR_CORRELATION),
    )


def test_factor_pair_contract_round_trips_and_is_symmetric() -> None:
    plan = _plan()
    swapped = _plan(swapped=True)
    assert OnlyResearchFactorPairOperand.from_dict(plan.first_operand.to_dict()) == plan.first_operand
    assert OnlyResearchFactorPairStatisticsDefinition.from_dict(plan.definition.to_dict()) == plan.definition
    assert OnlyResearchFactorPairStatisticsPlan.from_dict(plan.to_dict()) == plan
    assert plan.to_dict() == swapped.to_dict()
    assert plan.statistics_fingerprint == swapped.statistics_fingerprint
    assert plan.first_operand.candidate_fingerprint == "a" * 64


def test_factor_pair_identity_changes_for_dataset_operand_and_numeric_semantics() -> None:
    plan = _plan()
    assert replace(plan, dataset_snapshot_fingerprint="8" * 64).statistics_fingerprint != plan.statistics_fingerprint
    changed_operand = replace(plan.second_operand, candidate_fingerprint="7" * 64)
    assert replace(plan, second_operand=changed_operand).statistics_fingerprint != plan.statistics_fingerprint
    changed_numeric = replace(plan.definition.numeric, precision=37)
    with pytest.raises(ValueError, match="Decimal"):
        replace(plan.definition, numeric=changed_numeric)


@pytest.mark.parametrize(
    "change",
    (
        {"method": cast(OnlyResearchFactorPairStatisticsMethod, "FACTOR_CORRELATION")},
        {"minimum_observations": 1},
        {"alignment": cast(OnlyResearchFactorPairAlignment, "EXACT_COORDINATE_INTERSECTION")},
        {"pairing_policy": cast(OnlyResearchPairingPolicy, "PAIRWISE_COMPLETE")},
        {"universe_policy": cast(OnlyResearchUniversePolicy, "OBSERVED_PAIRWISE")},
        {"rank_tie_method": cast(OnlyResearchRankTieMethod, "AVERAGE")},
        {"weighting": cast(OnlyResearchWeighting, "EQUAL")},
        {"decimal_execution_policy": "other@1"},
        {"schema_version": 2},
    ),
)
def test_factor_pair_definition_fails_closed(change: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        replace(_plan().definition, **change)


def _observation(
    first: tuple[str, ...], second: tuple[str, ...], timestamp: int = 1
) -> tuple[OnlyResearchFactorPairAlignedObservation, ...]:
    return (
        OnlyResearchFactorPairAlignedObservation(
            timestamp,
            tuple(
                OnlyResearchFactorPairAlignedPair(chr(65 + index), Decimal(left), Decimal(right))
                for index, (left, right) in enumerate(zip(first, second, strict=True))
            ),
        ),
    )


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    (
        (("1", "2", "3"), ("2", "4", "6"), Decimal("1.000000000000")),
        (("1", "2", "3"), ("6", "4", "2"), Decimal("-1.000000000000")),
    ),
)
def test_factor_pair_pearson_goldens(first: tuple[str, ...], second: tuple[str, ...], expected: Decimal) -> None:
    rows = only_compute_research_factor_pair_statistics(_observation(first, second), _plan().definition)
    assert rows == (
        OnlyResearchFactorPairStatisticRow(1, expected, len(first), OnlyResearchFactorPairStatisticStatus.VALID),
    )


def test_factor_pair_rank_tie_golden_and_self_pair() -> None:
    definition = OnlyResearchFactorPairStatisticsDefinition(
        OnlyResearchFactorPairStatisticsMethod.FACTOR_RANK_CORRELATION
    )
    rows = only_compute_research_factor_pair_statistics(
        _observation(("1", "1", "3", "4"), ("10", "10", "30", "40")), definition
    )
    assert rows[0].statistic_value == Decimal("1.000000000000")
    self_rows = only_compute_research_factor_pair_statistics(
        _observation(("1", "2", "3"), ("1", "2", "3")), _plan().definition
    )
    assert self_rows[0].statistic_value == Decimal("1.000000000000")


def test_minimum_observations_and_zero_variance_precedence() -> None:
    insufficient = only_compute_research_factor_pair_statistics(_observation(("1",), ("2",)), _plan().definition)[0]
    assert (insufficient.statistic_value, insufficient.sample_count, insufficient.status) == (
        None,
        1,
        OnlyResearchFactorPairStatisticStatus.INSUFFICIENT_OBSERVATIONS,
    )
    cases = (
        (("1", "1", "1"), ("1", "2", "3"), OnlyResearchFactorPairStatisticStatus.ZERO_VARIANCE_FIRST_FACTOR),
        (("1", "2", "3"), ("1", "1", "1"), OnlyResearchFactorPairStatisticStatus.ZERO_VARIANCE_SECOND_FACTOR),
        (("1", "1", "1"), ("2", "2", "2"), OnlyResearchFactorPairStatisticStatus.ZERO_VARIANCE_FIRST_FACTOR),
    )
    for first, second, status in cases:
        row = only_compute_research_factor_pair_statistics(_observation(first, second), _plan().definition)[0]
        assert row.statistic_value is None and row.status is status


def test_factor_pair_decimal_execution_ignores_hostile_ambient_context() -> None:
    observations = _observation(("1", "2", "4"), ("2", "5", "9"))
    expected = only_compute_research_factor_pair_statistics(observations, _plan().definition)
    with localcontext() as caller:
        caller.prec = 4
        caller.rounding = ROUND_DOWN
        caller.Emin = -5
        caller.Emax = 5
        caller.clamp = 1
        caller.traps[Inexact] = True
        caller.flags[Rounded] = True
        flags = dict(caller.flags)
        assert only_compute_research_factor_pair_statistics(observations, _plan().definition) == expected
        assert dict(getcontext().flags) == flags


def _result(outputs: tuple[OnlyResearchCalculationNodeOutput, ...]) -> OnlyResearchCalculationResult:
    return OnlyResearchCalculationResult(cast(object, None), outputs)  # type: ignore[arg-type]


def _output(node: str, instrument: str, timestamps: list[int], values: list[Decimal | None]):
    return OnlyResearchCalculationNodeOutput(
        node,
        instrument,
        pa.table(
            {
                "ts_event_ns": pa.array(timestamps, type=pa.int64()),
                "value": pa.array(values, type=pa.decimal128(38, 12)),
            }
        ),
    )


def test_coordinate_intersection_preserves_structural_timestamps_and_canonical_order() -> None:
    first_node, second_node = "c" * 64, "f" * 64
    first = _result(
        (
            _output(first_node, "B", [1, 2, 4], [Decimal(2), None, Decimal(4)]),
            _output(first_node, "A", [1, 2, 3], [Decimal(1), None, Decimal(3)]),
        )
    )
    second = _result(
        (
            _output(second_node, "C", [1], [Decimal(99)]),
            _output(second_node, "B", [1, 2, 3], [Decimal(20), None, Decimal(30)]),
            _output(second_node, "A", [1, 2, 4], [Decimal(10), None, Decimal(40)]),
        )
    )
    aligned = only_align_research_factor_pair(first, second, _operand("a", "b", "c"), _operand("d", "e", "f"))
    assert tuple(item.ts_event_ns for item in aligned) == (1, 2)
    assert tuple(pair.instrument_id for pair in aligned[0].pairs) == ("A", "B")
    assert aligned[1].pairs == ()
    rows = only_compute_research_factor_pair_statistics(aligned, _plan().definition)
    assert rows[1] == OnlyResearchFactorPairStatisticRow(
        2, None, 0, OnlyResearchFactorPairStatisticStatus.INSUFFICIENT_OBSERVATIONS
    )


def test_coordinate_intersection_has_no_positional_zip_and_rejects_duplicate_coordinates() -> None:
    first_node, second_node = "c" * 64, "f" * 64
    first = _result((_output(first_node, "A", [1, 2], [Decimal(1), Decimal(2)]),))
    second = _result((_output(second_node, "A", [2, 3], [Decimal(20), Decimal(30)]),))
    aligned = only_align_research_factor_pair(first, second, _operand("a", "b", "c"), _operand("d", "e", "f"))
    assert len(aligned) == 1 and aligned[0].ts_event_ns == 2
    assert (aligned[0].pairs[0].first_value, aligned[0].pairs[0].second_value) == (
        Decimal(2),
        Decimal(20),
    )
    duplicate = _result(
        (
            _output(first_node, "A", [1], [Decimal(1)]),
            _output(first_node, "A", [1], [Decimal(2)]),
        )
    )
    with pytest.raises(OnlyResearchEvaluationError, match="duplicate"):
        only_align_research_factor_pair(duplicate, second, _operand("a", "b", "c"), _operand("d", "e", "f"))


def test_coordinate_intersection_covers_null_sides_partial_axes_and_no_overlap() -> None:
    first_node, second_node = "c" * 64, "f" * 64
    first = _result(
        (
            _output(first_node, "A", [1, 2, 3, 4, 5], [None, Decimal(1), None, Decimal(1), Decimal(5)]),
            _output(first_node, "B", [4, 5], [Decimal(2), Decimal(6)]),
            _output(first_node, "FIRST_ONLY", [4], [Decimal(9)]),
        )
    )
    second = _result(
        (
            _output(second_node, "A", [1, 2, 3, 4, 5], [Decimal(2), None, None, Decimal(2), Decimal(10)]),
            _output(second_node, "B", [4], [Decimal(4)]),
            _output(second_node, "SECOND_ONLY", [4], [Decimal(8)]),
        )
    )
    aligned = only_align_research_factor_pair(first, second, _operand("a", "b", "c"), _operand("d", "e", "f"))
    assert tuple(item.ts_event_ns for item in aligned) == (1, 2, 3, 4, 5)
    assert tuple(len(item.pairs) for item in aligned) == (0, 0, 0, 2, 1)
    rows = only_compute_research_factor_pair_statistics(aligned, _plan().definition)
    assert tuple(row.sample_count for row in rows) == (0, 0, 0, 2, 1)
    assert rows[3].status is OnlyResearchFactorPairStatisticStatus.VALID
    assert rows[4].status is OnlyResearchFactorPairStatisticStatus.INSUFFICIENT_OBSERVATIONS

    disjoint = only_align_research_factor_pair(
        _result((_output(first_node, "A", [10], [Decimal(1)]),)),
        _result((_output(second_node, "A", [11], [Decimal(2)]),)),
        _operand("a", "b", "c"),
        _operand("d", "e", "f"),
    )
    assert disjoint == ()


def test_factor_pair_row_and_plan_readers_reject_invalid_contracts() -> None:
    with pytest.raises(ValueError):
        OnlyResearchFactorPairStatisticRow(1, Decimal(2), 2, OnlyResearchFactorPairStatisticStatus.VALID)
    payload = _plan().to_dict()
    payload["unknown"] = True
    with pytest.raises(ValueError, match="fields"):
        OnlyResearchFactorPairStatisticsPlan.from_dict(payload)
    definition = _plan().definition.to_dict()
    cast(dict[str, object], definition["numeric"])["precision"] = 37
    with pytest.raises(ValueError, match="Decimal"):
        OnlyResearchFactorPairStatisticsDefinition.from_dict(definition)


def test_numeric_contract_constructor_rejects_wrong_semantics() -> None:
    wrong = OnlyNumericDefinition("DECIMAL", 38, Decimal("0.000000000001"), "ROUND_DOWN")
    with pytest.raises(ValueError, match="Decimal"):
        replace(_plan().definition, numeric=wrong)
