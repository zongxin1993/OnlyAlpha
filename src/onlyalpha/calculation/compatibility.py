"""Single semantic authority for Calculation DAG port compatibility."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.calculation.definition import (
    PREDICATE_OPERAND_SEMANTIC_TYPE,
    OnlyInputDefinition,
    OnlyOutputDefinition,
)


@dataclass(frozen=True, slots=True)
class OnlyCalculationCompatibility:
    compatible: bool
    reason: str | None = None


def only_calculation_output_compatibility(
    output: OnlyOutputDefinition,
    target: OnlyInputDefinition,
) -> OnlyCalculationCompatibility:
    if output.data_type is not target.data_type:
        return OnlyCalculationCompatibility(False, "data_type")
    if output.nullable and not target.nullable:
        return OnlyCalculationCompatibility(False, "nullability")
    if output.dimensions != target.dimensions:
        return OnlyCalculationCompatibility(False, "dimensions")
    # P8.4 internal Predicate primitives preserve the exact data type while
    # intentionally accepting any published/source series semantic role. The
    # wildcard is input-only and cannot weaken ordinary Calculation ports.
    if target.semantic_type != PREDICATE_OPERAND_SEMANTIC_TYPE and output.semantic_type != target.semantic_type:
        return OnlyCalculationCompatibility(False, "semantic_type")
    if target.semantic_type != PREDICATE_OPERAND_SEMANTIC_TYPE and output.unit != target.unit:
        return OnlyCalculationCompatibility(False, "unit")
    return OnlyCalculationCompatibility(True)
