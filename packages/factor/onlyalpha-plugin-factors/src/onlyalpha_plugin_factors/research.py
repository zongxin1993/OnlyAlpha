"""Exact Decimal finite-column RESEARCH Factor backends."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, localcontext

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.calculation import (
    OnlyCalculationDefinition,
    OnlyFactorScoreDirection,
)

_DECIMAL = pa.decimal128(38, 12)


class OnlyOfficialResearchFactorBackend:
    """Execute only the algorithm declared by an official Factor node."""

    def execute(
        self,
        definition: OnlyCalculationDefinition,
        inputs: Mapping[str, pa.Array | pa.ChunkedArray],
    ) -> Mapping[str, pa.Array]:
        if definition.type_id == "onlyalpha.factor.momentum" and definition.semantic_version == "1":
            return _momentum(definition, inputs)
        if definition.type_id == "onlyalpha.factor.cross_section_percentile" and definition.semantic_version == "1":
            return _percentile(definition, inputs)
        raise ValueError(f"unsupported official Factor: {definition.type_id}@{definition.semantic_version}")


def _momentum(
    definition: OnlyCalculationDefinition,
    inputs: Mapping[str, pa.Array | pa.ChunkedArray],
) -> Mapping[str, pa.Array]:
    _require_names(inputs, {"return_short", "return_long"})
    short = _decimal_values(inputs["return_short"])
    long = _decimal_values(inputs["return_long"])
    if len(short) != len(long):
        raise ValueError("Momentum input lengths differ")
    short_weight = _parameter_decimal(definition, "short_weight")
    long_weight = _parameter_decimal(definition, "long_weight")
    values = (
        None if left is None or right is None else _quantize(definition, short_weight * left + long_weight * right)
        for left, right in zip(short, long, strict=True)
    )
    return {"factor_value": pa.array(tuple(values), type=_DECIMAL)}


def _percentile(
    definition: OnlyCalculationDefinition,
    inputs: Mapping[str, pa.Array | pa.ChunkedArray],
) -> Mapping[str, pa.Array]:
    _require_names(inputs, {"factor_value"})
    values = _decimal_values(inputs["factor_value"])
    if definition.parameters.get("tie_method") != "AVERAGE":
        raise ValueError("Percentile scorer requires AVERAGE tie_method")
    direction = OnlyFactorScoreDirection(str(definition.parameters.get("direction")))
    eligible = sorted(value for value in values if value is not None)
    scores: dict[Decimal, Decimal] = {}
    count = len(eligible)
    if count == 1:
        scores[eligible[0]] = Decimal("0.5")
    elif count >= 2:
        index = 0
        while index < count:
            end = index + 1
            while end < count and eligible[end] == eligible[index]:
                end += 1
            average_rank = (Decimal(index) + Decimal(end - 1)) / Decimal(2)
            score = average_rank / Decimal(count - 1)
            if direction is OnlyFactorScoreDirection.LOWER_IS_BETTER:
                score = Decimal(1) - score
            scores[eligible[index]] = score
            index = end
    result = tuple(None if value is None else _quantize(definition, scores[value]) for value in values)
    return {"factor_score": pa.array(result, type=_DECIMAL)}


def _quantize(definition: OnlyCalculationDefinition, value: Decimal) -> Decimal:
    quantum = definition.numeric.output_quantum
    if quantum is None:
        raise ValueError("official Factor requires output_quantum")
    with localcontext() as context:
        context.prec = definition.numeric.precision
        context.rounding = definition.numeric.rounding
        return value.quantize(quantum)


def _decimal_values(array: pa.Array | pa.ChunkedArray) -> tuple[Decimal | None, ...]:
    if not pa.types.is_decimal(array.type):
        raise ValueError("official Factor inputs must use Arrow Decimal")
    return tuple(array.to_pylist())


def _parameter_decimal(definition: OnlyCalculationDefinition, name: str) -> Decimal:
    value = definition.parameters.get(name)
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal")
    return value


def _require_names(inputs: Mapping[str, object], expected: set[str]) -> None:
    if set(inputs) != expected:
        raise ValueError(f"Factor input names must be {sorted(expected)}")
