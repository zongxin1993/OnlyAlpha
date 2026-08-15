"""Exact instrument and observation-time pair alignment."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.research.calculation.result import OnlyResearchCalculationResult

from .errors import OnlyResearchEvaluationError
from .reference import OnlyResearchFeatureSeriesReference, OnlyResearchTargetSeriesReference


@dataclass(frozen=True, slots=True)
class OnlyResearchAlignedPair:
    instrument_id: str
    feature_value: Decimal
    target_value: Decimal


@dataclass(frozen=True, slots=True)
class OnlyResearchAlignedObservation:
    ts_event_ns: int
    pairs: tuple[OnlyResearchAlignedPair, ...]


def only_align_research_series(
    feature_result: OnlyResearchCalculationResult,
    target_result: OnlyResearchCalculationResult,
    feature: OnlyResearchFeatureSeriesReference,
    target: OnlyResearchTargetSeriesReference,
) -> tuple[OnlyResearchAlignedObservation, ...]:
    feature_partitions = _series(feature_result, feature.node_fingerprint, feature.output_name, "feature")
    target_partitions = _series(target_result, target.node_fingerprint, target.output_name, "target")
    if set(feature_partitions) != set(target_partitions):
        raise OnlyResearchEvaluationError("STATISTICS_AXIS_CORRUPT", "instrument axes differ")
    planes: dict[int, list[OnlyResearchAlignedPair]] = {}
    for instrument in sorted(feature_partitions):
        feature_axis, feature_values = feature_partitions[instrument]
        target_axis, target_values = target_partitions[instrument]
        if feature_axis != target_axis:
            raise OnlyResearchEvaluationError("STATISTICS_AXIS_CORRUPT", f"timestamp axis differs for {instrument}")
        for timestamp, feature_value, target_value in zip(feature_axis, feature_values, target_values, strict=True):
            bucket = planes.setdefault(timestamp, [])
            if feature_value is None or target_value is None:
                continue
            bucket.append(OnlyResearchAlignedPair(instrument, feature_value, target_value))
    return tuple(
        OnlyResearchAlignedObservation(timestamp, tuple(sorted(pairs, key=lambda item: item.instrument_id)))
        for timestamp, pairs in sorted(planes.items())
    )


def _series(
    result: OnlyResearchCalculationResult,
    node_fingerprint: str,
    output_name: str,
    label: str,
) -> dict[str, tuple[tuple[int, ...], tuple[Decimal | None, ...]]]:
    partitions = [output for output in result.outputs if output.node_fingerprint == node_fingerprint]
    if not partitions:
        raise OnlyResearchEvaluationError("STATISTICS_REFERENCE_INVALID", f"{label} node output is absent")
    values: dict[str, tuple[tuple[int, ...], tuple[Decimal | None, ...]]] = {}
    for partition in partitions:
        if partition.instrument_id in values:
            raise OnlyResearchEvaluationError("STATISTICS_AXIS_CORRUPT", f"duplicate {label} instrument")
        table = partition.table
        if table.schema.get_field_index(output_name) < 0:
            raise OnlyResearchEvaluationError("STATISTICS_REFERENCE_INVALID", f"{label} output is absent")
        column = table.column(output_name)
        timestamp = table.column("ts_event_ns")
        if not pa.types.is_decimal(column.type) or timestamp.type != pa.int64() or timestamp.null_count:
            raise OnlyResearchEvaluationError("STATISTICS_AXIS_CORRUPT", f"{label} series type is invalid")
        axis = tuple(timestamp.to_pylist())
        if axis != tuple(sorted(axis)) or len(axis) != len(set(axis)):
            raise OnlyResearchEvaluationError("STATISTICS_AXIS_CORRUPT", f"{label} timestamp axis is invalid")
        raw_values = tuple(column.to_pylist())
        if any(value is not None and (not isinstance(value, Decimal) or not value.is_finite()) for value in raw_values):
            raise OnlyResearchEvaluationError("STATISTICS_AXIS_CORRUPT", f"{label} value is invalid")
        values[partition.instrument_id] = (axis, raw_values)
    return values
