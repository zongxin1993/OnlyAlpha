"""Deterministic Factor-Pair correlation execution."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Protocol

from onlyalpha.calculation import (
    FACTOR_SCORE_SEMANTIC_TYPE,
    FACTOR_VALUE_SEMANTIC_TYPE,
    OnlyCalculationKind,
    only_decimal_context,
    only_quantize_decimal,
)
from onlyalpha.research.calculation.errors import OnlyResearchCalculationResultStoreError
from onlyalpha.research.calculation.result import OnlyResearchCalculationResult

from ..errors import OnlyResearchEvaluationError, OnlyResearchStatisticsResultStoreError
from .alignment import OnlyResearchFactorPairAlignedObservation, only_align_research_factor_pair
from .definition import OnlyResearchFactorPairStatisticsDefinition, OnlyResearchFactorPairStatisticsMethod
from .plan import OnlyResearchFactorPairStatisticsPlan
from .result import (
    OnlyResearchFactorPairStatisticRow,
    OnlyResearchFactorPairStatisticsDisposition,
    OnlyResearchFactorPairStatisticsOutcome,
    OnlyResearchFactorPairStatisticsResult,
    OnlyResearchFactorPairStatisticStatus,
)


@dataclass(frozen=True, slots=True)
class OnlyResearchFactorPairStatisticsExecution:
    plan: OnlyResearchFactorPairStatisticsPlan
    first_calculation_result_fingerprint: str
    second_calculation_result_fingerprint: str
    dataset_snapshot_fingerprint: str
    rows: tuple[OnlyResearchFactorPairStatisticRow, ...]


class _CalculationResultStore(Protocol):
    def load_verified(self, calculation_fingerprint: str) -> OnlyResearchCalculationResult: ...


class _FactorPairResultStore(Protocol):
    def load_verified(self, statistics_fingerprint: str) -> OnlyResearchFactorPairStatisticsResult: ...

    def commit(
        self, execution: OnlyResearchFactorPairStatisticsExecution
    ) -> OnlyResearchFactorPairStatisticsResult: ...


class OnlyResearchFactorPairStatisticsExecutor:
    def __init__(self, calculation_result_store: _CalculationResultStore, result_store: _FactorPairResultStore) -> None:
        self._calculation_result_store = calculation_result_store
        self._result_store = result_store

    def execute(self, plan: OnlyResearchFactorPairStatisticsPlan) -> OnlyResearchFactorPairStatisticsOutcome:
        if not isinstance(plan, OnlyResearchFactorPairStatisticsPlan):
            raise OnlyResearchEvaluationError("FACTOR_PAIR_PLAN_INVALID", "execute requires a Factor-Pair Plan")
        try:
            existing = self._result_store.load_verified(plan.statistics_fingerprint)
        except OnlyResearchStatisticsResultStoreError as exc:
            if exc.code != "FACTOR_PAIR_STATISTICS_RESULT_NOT_FOUND":
                raise
        except Exception as exc:
            raise OnlyResearchEvaluationError("FACTOR_PAIR_RESULT_REUSE_FAILED", str(exc)) from exc
        else:
            return _outcome(plan, existing, OnlyResearchFactorPairStatisticsDisposition.REUSED)
        first = self._load(plan.first_operand.series.calculation_fingerprint, "first")
        second = self._load(plan.second_operand.series.calculation_fingerprint, "second")
        dataset = _validate_factor_pair_upstream(plan, first, second)
        aligned = only_align_research_factor_pair(first, second, plan.first_operand, plan.second_operand)
        rows = only_compute_research_factor_pair_statistics(aligned, plan.definition)
        execution = OnlyResearchFactorPairStatisticsExecution(
            plan,
            first.manifest.calculation_result_fingerprint,
            second.manifest.calculation_result_fingerprint,
            dataset,
            rows,
        )
        try:
            committed = self._result_store.commit(execution)
        except OnlyResearchStatisticsResultStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchEvaluationError("FACTOR_PAIR_RESULT_COMMIT_FAILED", str(exc)) from exc
        return _outcome(plan, committed, OnlyResearchFactorPairStatisticsDisposition.EXECUTED)

    def _load(self, fingerprint: str, label: str) -> OnlyResearchCalculationResult:
        try:
            return self._calculation_result_store.load_verified(fingerprint)
        except OnlyResearchCalculationResultStoreError as exc:
            raise OnlyResearchEvaluationError("FACTOR_PAIR_UPSTREAM_INVALID", f"{label}: {exc.code}") from exc
        except Exception as exc:
            raise OnlyResearchEvaluationError("FACTOR_PAIR_UPSTREAM_INVALID", label) from exc


def only_compute_research_factor_pair_statistics(
    observations: tuple[OnlyResearchFactorPairAlignedObservation, ...],
    definition: OnlyResearchFactorPairStatisticsDefinition,
) -> tuple[OnlyResearchFactorPairStatisticRow, ...]:
    if not isinstance(definition, OnlyResearchFactorPairStatisticsDefinition):
        raise OnlyResearchEvaluationError("FACTOR_PAIR_DEFINITION_INVALID", "definition contract is invalid")
    timestamps = tuple(item.ts_event_ns for item in observations)
    if timestamps != tuple(sorted(timestamps)) or len(timestamps) != len(set(timestamps)):
        raise OnlyResearchEvaluationError("FACTOR_PAIR_AXIS_CORRUPT", "timestamps are not canonical")
    rows: list[OnlyResearchFactorPairStatisticRow] = []
    for observation in observations:
        instruments = tuple(pair.instrument_id for pair in observation.pairs)
        if instruments != tuple(sorted(instruments)) or len(instruments) != len(set(instruments)):
            raise OnlyResearchEvaluationError("FACTOR_PAIR_AXIS_CORRUPT", "instruments are not canonical")
        first = tuple(pair.first_value for pair in observation.pairs)
        second = tuple(pair.second_value for pair in observation.pairs)
        if len(first) < definition.minimum_observations:
            rows.append(
                OnlyResearchFactorPairStatisticRow(
                    observation.ts_event_ns,
                    None,
                    len(first),
                    OnlyResearchFactorPairStatisticStatus.INSUFFICIENT_OBSERVATIONS,
                )
            )
            continue
        with localcontext(only_decimal_context(definition.numeric)):
            if definition.method is OnlyResearchFactorPairStatisticsMethod.FACTOR_RANK_CORRELATION:
                first = _average_ranks(first)
                second = _average_ranks(second)
            value, status = _pearson(first, second, definition)
        rows.append(OnlyResearchFactorPairStatisticRow(observation.ts_event_ns, value, len(first), status))
    return tuple(rows)


def _validate_factor_pair_upstream(
    plan: OnlyResearchFactorPairStatisticsPlan,
    first: OnlyResearchCalculationResult,
    second: OnlyResearchCalculationResult,
) -> str:
    if first.manifest.calculation_fingerprint != plan.first_operand.series.calculation_fingerprint:
        raise OnlyResearchEvaluationError("FACTOR_PAIR_REFERENCE_INVALID", "first Calculation identity mismatch")
    if second.manifest.calculation_fingerprint != plan.second_operand.series.calculation_fingerprint:
        raise OnlyResearchEvaluationError("FACTOR_PAIR_REFERENCE_INVALID", "second Calculation identity mismatch")
    first_dataset = first.manifest.dataset_snapshot_fingerprint
    second_dataset = second.manifest.dataset_snapshot_fingerprint
    if first_dataset != second_dataset or first_dataset != plan.dataset_snapshot_fingerprint:
        raise OnlyResearchEvaluationError("FACTOR_PAIR_DATASET_MISMATCH", "Factor-Pair Dataset bindings differ")
    _validate_factor_port(
        first, plan.first_operand.series.node_fingerprint, plan.first_operand.series.output_name, "first"
    )
    _validate_factor_port(
        second, plan.second_operand.series.node_fingerprint, plan.second_operand.series.output_name, "second"
    )
    return first_dataset


def _validate_factor_port(
    result: OnlyResearchCalculationResult, node_fingerprint: str, output_name: str, label: str
) -> None:
    nodes = {node.fingerprint: node.definition for node in result.manifest.calculation_graph.ordered_nodes}
    definition = nodes.get(node_fingerprint)
    if definition is None or definition.kind is not OnlyCalculationKind.FACTOR:
        raise OnlyResearchEvaluationError("FACTOR_PAIR_REFERENCE_INVALID", f"{label} node is not a Factor")
    output = {item.name: item for item in definition.outputs}.get(output_name)
    if output is None or output.semantic_type not in {FACTOR_VALUE_SEMANTIC_TYPE, FACTOR_SCORE_SEMANTIC_TYPE}:
        raise OnlyResearchEvaluationError(
            "FACTOR_PAIR_REFERENCE_INVALID", f"{label} output is not a Factor value/score"
        )


def _average_ranks(values: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
    ordered = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    ranks = [Decimal(0)] * len(values)
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        rank = (Decimal(index + 1) + Decimal(end)) / Decimal(2)
        for position in range(index, end):
            ranks[ordered[position][0]] = rank
        index = end
    return tuple(ranks)


def _pearson(
    first: tuple[Decimal, ...],
    second: tuple[Decimal, ...],
    definition: OnlyResearchFactorPairStatisticsDefinition,
) -> tuple[Decimal | None, OnlyResearchFactorPairStatisticStatus]:
    count = Decimal(len(first))
    first_mean = sum(first, Decimal(0)) / count
    second_mean = sum(second, Decimal(0)) / count
    first_delta = tuple(value - first_mean for value in first)
    second_delta = tuple(value - second_mean for value in second)
    first_variance = sum((value * value for value in first_delta), Decimal(0))
    second_variance = sum((value * value for value in second_delta), Decimal(0))
    if first_variance == 0:
        return None, OnlyResearchFactorPairStatisticStatus.ZERO_VARIANCE_FIRST_FACTOR
    if second_variance == 0:
        return None, OnlyResearchFactorPairStatisticStatus.ZERO_VARIANCE_SECOND_FACTOR
    covariance = sum((left * right for left, right in zip(first_delta, second_delta, strict=True)), Decimal(0))
    correlation = covariance / (first_variance * second_variance).sqrt()
    value = only_quantize_decimal(definition.numeric, correlation)
    quantum = definition.numeric.output_quantum
    if quantum is None:
        raise OnlyResearchEvaluationError("FACTOR_PAIR_DEFINITION_INVALID", "missing output quantum")
    if value > 1:
        value = only_quantize_decimal(definition.numeric, Decimal(1))
    elif value < -1:
        value = only_quantize_decimal(definition.numeric, Decimal(-1))
    return value, OnlyResearchFactorPairStatisticStatus.VALID


def _outcome(
    plan: OnlyResearchFactorPairStatisticsPlan,
    result: OnlyResearchFactorPairStatisticsResult,
    disposition: OnlyResearchFactorPairStatisticsDisposition,
) -> OnlyResearchFactorPairStatisticsOutcome:
    if result.manifest.statistics_fingerprint != plan.statistics_fingerprint or result.manifest.plan != plan:
        raise OnlyResearchEvaluationError("FACTOR_PAIR_RESULT_INVALID", "Result does not match Factor-Pair Plan")
    return OnlyResearchFactorPairStatisticsOutcome(
        disposition,
        result.manifest.statistics_fingerprint,
        result.manifest.statistics_result_fingerprint,
    )
