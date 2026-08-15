"""Deterministic IC/Rank IC computation and verified reuse orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Protocol

from onlyalpha.calculation import (
    FACTOR_SCORE_SEMANTIC_TYPE,
    FACTOR_VALUE_SEMANTIC_TYPE,
    TARGET_VALUE_SEMANTIC_TYPE,
    OnlyCalculationKind,
)
from onlyalpha.research.calculation.errors import OnlyResearchCalculationResultStoreError
from onlyalpha.research.calculation.result import OnlyResearchCalculationResult

from .alignment import OnlyResearchAlignedObservation, only_align_research_series
from .definition import OnlyResearchStatisticsDefinition, OnlyResearchStatisticsMethod
from .errors import OnlyResearchEvaluationError, OnlyResearchStatisticsResultStoreError
from .plan import OnlyResearchStatisticsPlan
from .result import (
    OnlyResearchStatisticRow,
    OnlyResearchStatisticsDisposition,
    OnlyResearchStatisticsOutcome,
    OnlyResearchStatisticsResult,
    OnlyResearchStatisticStatus,
)


@dataclass(frozen=True, slots=True)
class OnlyResearchStatisticsExecution:
    plan: OnlyResearchStatisticsPlan
    feature_calculation_result_fingerprint: str
    target_calculation_result_fingerprint: str
    dataset_snapshot_fingerprint: str
    rows: tuple[OnlyResearchStatisticRow, ...]


class _CalculationResultStore(Protocol):
    def load_verified(self, calculation_fingerprint: str) -> OnlyResearchCalculationResult: ...


class _StatisticsResultStore(Protocol):
    def load_verified(self, statistics_fingerprint: str) -> OnlyResearchStatisticsResult: ...

    def commit(self, execution: OnlyResearchStatisticsExecution) -> OnlyResearchStatisticsResult: ...


class OnlyResearchStatisticsExecutor:
    def __init__(
        self,
        calculation_result_store: _CalculationResultStore,
        statistics_result_store: _StatisticsResultStore,
    ) -> None:
        self._calculation_result_store = calculation_result_store
        self._statistics_result_store = statistics_result_store

    def execute(self, plan: OnlyResearchStatisticsPlan) -> OnlyResearchStatisticsOutcome:
        if not isinstance(plan, OnlyResearchStatisticsPlan):
            raise OnlyResearchEvaluationError("STATISTICS_PLAN_INVALID", "execute requires a Statistics Plan")
        try:
            existing = self._statistics_result_store.load_verified(plan.statistics_fingerprint)
        except OnlyResearchStatisticsResultStoreError as exc:
            if exc.code != "STATISTICS_RESULT_NOT_FOUND":
                raise
        except Exception as exc:
            raise OnlyResearchEvaluationError("STATISTICS_RESULT_REUSE_FAILED", str(exc)) from exc
        else:
            return _outcome(plan, existing, OnlyResearchStatisticsDisposition.REUSED)

        feature_result = self._load(plan.feature.calculation_fingerprint, "feature")
        target_result = self._load(plan.target.calculation_fingerprint, "target")
        dataset = _validate_upstream(plan, feature_result, target_result)
        observations = only_align_research_series(feature_result, target_result, plan.feature, plan.target)
        rows = only_compute_research_statistics(observations, plan.definition)
        execution = OnlyResearchStatisticsExecution(
            plan,
            feature_result.manifest.calculation_result_fingerprint,
            target_result.manifest.calculation_result_fingerprint,
            dataset,
            rows,
        )
        try:
            committed = self._statistics_result_store.commit(execution)
        except OnlyResearchStatisticsResultStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchEvaluationError("STATISTICS_RESULT_COMMIT_FAILED", str(exc)) from exc
        return _outcome(plan, committed, OnlyResearchStatisticsDisposition.EXECUTED)

    def _load(self, calculation_fingerprint: str, label: str) -> OnlyResearchCalculationResult:
        try:
            return self._calculation_result_store.load_verified(calculation_fingerprint)
        except OnlyResearchCalculationResultStoreError as exc:
            raise OnlyResearchEvaluationError("STATISTICS_UPSTREAM_INVALID", f"{label}: {exc.code}") from exc
        except Exception as exc:
            raise OnlyResearchEvaluationError("STATISTICS_UPSTREAM_INVALID", label) from exc


def only_compute_research_statistics(
    observations: tuple[OnlyResearchAlignedObservation, ...],
    definition: OnlyResearchStatisticsDefinition,
) -> tuple[OnlyResearchStatisticRow, ...]:
    if not isinstance(definition, OnlyResearchStatisticsDefinition):
        raise OnlyResearchEvaluationError("STATISTICS_DEFINITION_INVALID", "definition contract is invalid")
    timestamps = tuple(item.ts_event_ns for item in observations)
    if timestamps != tuple(sorted(timestamps)) or len(timestamps) != len(set(timestamps)):
        raise OnlyResearchEvaluationError("STATISTICS_AXIS_CORRUPT", "observation timestamps are not canonical")
    rows: list[OnlyResearchStatisticRow] = []
    for observation in observations:
        feature = tuple(pair.feature_value for pair in observation.pairs)
        target = tuple(pair.target_value for pair in observation.pairs)
        if len(feature) < definition.minimum_observations:
            rows.append(
                OnlyResearchStatisticRow(
                    observation.ts_event_ns,
                    None,
                    len(feature),
                    OnlyResearchStatisticStatus.INSUFFICIENT_OBSERVATIONS,
                )
            )
            continue
        if definition.method is OnlyResearchStatisticsMethod.RANK_IC:
            feature = _average_ranks(feature)
            target = _average_ranks(target)
        value, status = _pearson(feature, target, definition)
        rows.append(OnlyResearchStatisticRow(observation.ts_event_ns, value, len(feature), status))
    return tuple(rows)


def _validate_upstream(
    plan: OnlyResearchStatisticsPlan,
    feature_result: OnlyResearchCalculationResult,
    target_result: OnlyResearchCalculationResult,
) -> str:
    if feature_result.manifest.calculation_fingerprint != plan.feature.calculation_fingerprint:
        raise OnlyResearchEvaluationError("STATISTICS_REFERENCE_INVALID", "feature Calculation identity mismatch")
    if target_result.manifest.calculation_fingerprint != plan.target.calculation_fingerprint:
        raise OnlyResearchEvaluationError("STATISTICS_REFERENCE_INVALID", "target Calculation identity mismatch")
    feature_dataset = feature_result.manifest.dataset_snapshot_fingerprint
    target_dataset = target_result.manifest.dataset_snapshot_fingerprint
    if feature_dataset != target_dataset:
        raise OnlyResearchEvaluationError("STATISTICS_DATASET_MISMATCH", "Feature and Target Dataset Snapshots differ")
    _validate_port(
        feature_result,
        plan.feature.node_fingerprint,
        plan.feature.output_name,
        OnlyCalculationKind.FACTOR,
        {FACTOR_VALUE_SEMANTIC_TYPE, FACTOR_SCORE_SEMANTIC_TYPE},
        "feature",
    )
    _validate_port(
        target_result,
        plan.target.node_fingerprint,
        plan.target.output_name,
        OnlyCalculationKind.TARGET,
        {TARGET_VALUE_SEMANTIC_TYPE},
        "target",
    )
    return feature_dataset


def _validate_port(
    result: OnlyResearchCalculationResult,
    node_fingerprint: str,
    output_name: str,
    kind: OnlyCalculationKind,
    semantic_types: set[str],
    label: str,
) -> None:
    nodes = {node.fingerprint: node.definition for node in result.manifest.calculation_graph.ordered_nodes}
    definition = nodes.get(node_fingerprint)
    if definition is None or definition.kind is not kind:
        raise OnlyResearchEvaluationError("STATISTICS_REFERENCE_INVALID", f"{label} node semantic kind is invalid")
    outputs = {output.name: output for output in definition.outputs}
    output = outputs.get(output_name)
    if output is None or output.semantic_type not in semantic_types:
        raise OnlyResearchEvaluationError("STATISTICS_REFERENCE_INVALID", f"{label} output semantic type is invalid")


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
    feature: tuple[Decimal, ...],
    target: tuple[Decimal, ...],
    definition: OnlyResearchStatisticsDefinition,
) -> tuple[Decimal | None, OnlyResearchStatisticStatus]:
    with localcontext() as context:
        context.prec = definition.numeric.precision
        context.rounding = definition.numeric.rounding
        count = Decimal(len(feature))
        feature_mean = sum(feature, Decimal(0)) / count
        target_mean = sum(target, Decimal(0)) / count
        feature_delta = tuple(value - feature_mean for value in feature)
        target_delta = tuple(value - target_mean for value in target)
        feature_variance = sum((value * value for value in feature_delta), Decimal(0))
        target_variance = sum((value * value for value in target_delta), Decimal(0))
        if feature_variance == 0:
            return None, OnlyResearchStatisticStatus.ZERO_VARIANCE_FEATURE
        if target_variance == 0:
            return None, OnlyResearchStatisticStatus.ZERO_VARIANCE_TARGET
        covariance = sum((left * right for left, right in zip(feature_delta, target_delta, strict=True)), Decimal(0))
        correlation = covariance / (feature_variance * target_variance).sqrt()
        quantum = definition.numeric.output_quantum
        if quantum is None:  # guarded by Definition
            raise OnlyResearchEvaluationError("STATISTICS_DEFINITION_INVALID", "missing output quantum")
        value = correlation.quantize(quantum)
        if value > 1:
            value = Decimal(1).quantize(quantum)
        elif value < -1:
            value = Decimal(-1).quantize(quantum)
        return value, OnlyResearchStatisticStatus.VALID


def _outcome(
    plan: OnlyResearchStatisticsPlan,
    result: OnlyResearchStatisticsResult,
    disposition: OnlyResearchStatisticsDisposition,
) -> OnlyResearchStatisticsOutcome:
    if result.manifest.statistics_fingerprint != plan.statistics_fingerprint or result.manifest.plan != plan:
        raise OnlyResearchEvaluationError(
            "STATISTICS_RESULT_INVALID", "Result authority does not match Statistics Plan"
        )
    return OnlyResearchStatisticsOutcome(
        disposition,
        result.manifest.statistics_fingerprint,
        result.manifest.statistics_result_fingerprint,
    )
