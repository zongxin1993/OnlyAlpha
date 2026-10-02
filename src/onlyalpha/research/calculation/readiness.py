"""Complete point-level readiness validation, never inferred from numeric values."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.calculation.definition import OnlyCalculationDefinition

from .errors import OnlyResearchCalculationError

RESEARCH_CALCULATION_READINESS_CONTRACT_VERSION = 1


class OnlyResearchReadinessState(StrEnum):
    PARTIAL = "PARTIAL"
    READY = "READY"
    UNAVAILABLE = "UNAVAILABLE"


class OnlyResearchReadinessReason(StrEnum):
    NONE = "NONE"
    WARMUP_INCOMPLETE = "WARMUP_INCOMPLETE"
    VALUE_UNDEFINED = "VALUE_UNDEFINED"
    INPUT_UNAVAILABLE = "INPUT_UNAVAILABLE"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class OnlyResearchOutputReadiness:
    states: pa.Array | pa.ChunkedArray
    reasons: pa.Array | pa.ChunkedArray


def only_validate_research_output_readiness(
    definition: OnlyCalculationDefinition,
    outputs: Mapping[str, pa.Array | pa.ChunkedArray],
    readiness: Mapping[str, OnlyResearchOutputReadiness],
    *,
    row_count: int,
) -> None:
    """Validate structural pairing; numeric contracts and producer proof are separate."""

    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count < 0:
        raise OnlyResearchCalculationError("RESEARCH_READINESS_INVALID", "row_count must be a nonnegative integer")
    expected = {item.name: item for item in definition.outputs}
    if (
        not isinstance(outputs, Mapping)
        or not isinstance(readiness, Mapping)
        or set(outputs) != set(expected)
        or set(readiness) != set(expected)
    ):
        raise OnlyResearchCalculationError("RESEARCH_READINESS_INVALID", "output/readiness names must match Definition")
    for name in sorted(expected):
        values = outputs[name]
        evidence = readiness[name]
        if not isinstance(values, (pa.Array, pa.ChunkedArray)) or len(values) != row_count:
            raise OnlyResearchCalculationError("RESEARCH_READINESS_INVALID", f"{name} value row count")
        if not isinstance(evidence, OnlyResearchOutputReadiness):
            raise OnlyResearchCalculationError("RESEARCH_READINESS_INVALID", f"{name} readiness carrier")
        for field, array in (("states", evidence.states), ("reasons", evidence.reasons)):
            if (
                not isinstance(array, (pa.Array, pa.ChunkedArray))
                or not pa.types.is_string(array.type)
                or array.null_count
                or len(array) != row_count
            ):
                raise OnlyResearchCalculationError(
                    "RESEARCH_READINESS_INVALID", f"{name} {field} must be non-null aligned Arrow strings"
                )
        for index, (value, state_value, reason_value) in enumerate(
            zip(values, evidence.states, evidence.reasons, strict=True)
        ):
            try:
                state = OnlyResearchReadinessState(state_value.as_py())
                reason = OnlyResearchReadinessReason(reason_value.as_py())
            except ValueError as exc:
                raise OnlyResearchCalculationError(
                    "RESEARCH_READINESS_INVALID", f"{name} row {index} noncanonical state/reason"
                ) from exc
            if state is OnlyResearchReadinessState.PARTIAL:
                valid = reason is OnlyResearchReadinessReason.WARMUP_INCOMPLETE and (
                    value.is_valid or expected[name].nullable
                )
            elif state is OnlyResearchReadinessState.READY:
                valid = (
                    reason is OnlyResearchReadinessReason.NONE
                    if value.is_valid
                    else expected[name].nullable and reason is OnlyResearchReadinessReason.VALUE_UNDEFINED
                )
            else:
                valid = not value.is_valid and reason in (
                    OnlyResearchReadinessReason.INPUT_UNAVAILABLE,
                    OnlyResearchReadinessReason.DEPENDENCY_UNAVAILABLE,
                )
            if not valid:
                raise OnlyResearchCalculationError(
                    "RESEARCH_READINESS_INVALID", f"{name} row {index} contradictory state/reason/value"
                )
