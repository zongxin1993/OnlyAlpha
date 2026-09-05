"""Exact structural coordinate-intersection alignment for Factor pairs."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.research.calculation.result import OnlyResearchCalculationResult

from ..errors import OnlyResearchEvaluationError
from .reference import OnlyResearchFactorPairOperand


@dataclass(frozen=True, slots=True)
class OnlyResearchFactorPairAlignedPair:
    instrument_id: str
    first_value: Decimal
    second_value: Decimal


@dataclass(frozen=True, slots=True)
class OnlyResearchFactorPairAlignedObservation:
    ts_event_ns: int
    pairs: tuple[OnlyResearchFactorPairAlignedPair, ...]


def only_align_research_factor_pair(
    first_result: OnlyResearchCalculationResult,
    second_result: OnlyResearchCalculationResult,
    first_operand: OnlyResearchFactorPairOperand,
    second_operand: OnlyResearchFactorPairOperand,
) -> tuple[OnlyResearchFactorPairAlignedObservation, ...]:
    first = _coordinates(first_result, first_operand, "first")
    second = _coordinates(second_result, second_operand, "second")
    shared = sorted(set(first).intersection(second), key=lambda item: (item[1], item[0]))
    planes: dict[int, list[OnlyResearchFactorPairAlignedPair]] = {}
    for instrument_id, timestamp in shared:
        bucket = planes.setdefault(timestamp, [])
        first_value = first[(instrument_id, timestamp)]
        second_value = second[(instrument_id, timestamp)]
        if first_value is not None and second_value is not None:
            bucket.append(OnlyResearchFactorPairAlignedPair(instrument_id, first_value, second_value))
    return tuple(
        OnlyResearchFactorPairAlignedObservation(timestamp, tuple(pairs)) for timestamp, pairs in sorted(planes.items())
    )


def _coordinates(
    result: OnlyResearchCalculationResult,
    operand: OnlyResearchFactorPairOperand,
    label: str,
) -> dict[tuple[str, int], Decimal | None]:
    series = operand.series
    partitions = [output for output in result.outputs if output.node_fingerprint == series.node_fingerprint]
    if not partitions:
        raise OnlyResearchEvaluationError("FACTOR_PAIR_REFERENCE_INVALID", f"{label} node output is absent")
    coordinates: dict[tuple[str, int], Decimal | None] = {}
    for partition in partitions:
        table = partition.table
        if table.schema.get_field_index(series.output_name) < 0:
            raise OnlyResearchEvaluationError("FACTOR_PAIR_REFERENCE_INVALID", f"{label} output is absent")
        column = table.column(series.output_name)
        timestamp = table.column("ts_event_ns")
        if not pa.types.is_decimal(column.type) or timestamp.type != pa.int64() or timestamp.null_count:
            raise OnlyResearchEvaluationError("FACTOR_PAIR_AXIS_CORRUPT", f"{label} series type is invalid")
        raw_timestamps = timestamp.to_pylist()
        raw_values = column.to_pylist()
        for raw_timestamp, value in zip(raw_timestamps, raw_values, strict=True):
            coordinate = (partition.instrument_id, raw_timestamp)
            if coordinate in coordinates:
                raise OnlyResearchEvaluationError(
                    "FACTOR_PAIR_AXIS_CORRUPT", f"duplicate {label} structural coordinate"
                )
            if value is not None and (not isinstance(value, Decimal) or not value.is_finite()):
                raise OnlyResearchEvaluationError("FACTOR_PAIR_AXIS_CORRUPT", f"{label} value is invalid")
            coordinates[coordinate] = value
    return coordinates
