"""Exact Decimal finite-column RESEARCH Operator backends."""

from collections.abc import Mapping
from decimal import Decimal, localcontext

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.calculation import OnlyCalculationDefinition

_DECIMAL = pa.decimal128(38, 12)


class OnlyOfficialResearchOperatorBackend:
    def execute(
        self,
        definition: OnlyCalculationDefinition,
        inputs: Mapping[str, pa.Array | pa.ChunkedArray],
    ) -> Mapping[str, pa.Array]:
        if set(inputs) != {"value"}:
            raise ValueError("Operator input names must be ['value']")
        values = _decimal_values(inputs["value"])
        if definition.type_id == "onlyalpha.operator.rolling_mean" and definition.semantic_version == "1":
            return {"value": pa.array(_rolling_mean(definition, values), type=_DECIMAL)}
        if definition.type_id == "onlyalpha.operator.cross_section_percentile" and definition.semantic_version == "1":
            return {"percentile": pa.array(_percentile(definition, values), type=_DECIMAL)}
        raise ValueError(f"unsupported official Operator: {definition.type_id}@{definition.semantic_version}")


def _rolling_mean(
    definition: OnlyCalculationDefinition, values: tuple[Decimal | None, ...]
) -> tuple[Decimal | None, ...]:
    period = int(str(definition.parameters["period"]))
    result: list[Decimal | None] = []
    for index in range(len(values)):
        window = values[max(0, index - period + 1) : index + 1]
        result.append(
            None
            if len(window) < period or any(value is None for value in window)
            else _quantize(definition, sum((value for value in window if value is not None), Decimal(0)) / period)
        )
    return tuple(result)


def _percentile(
    definition: OnlyCalculationDefinition, values: tuple[Decimal | None, ...]
) -> tuple[Decimal | None, ...]:
    if definition.parameters["tie_method"] != "AVERAGE":
        raise ValueError("Cross-section percentile requires AVERAGE tie_method")
    direction = str(definition.parameters["direction"])
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
            score = ((Decimal(index) + Decimal(end - 1)) / 2) / Decimal(count - 1)
            if direction == "LOWER_IS_BETTER":
                score = Decimal(1) - score
            scores[eligible[index]] = score
            index = end
    return tuple(None if value is None else _quantize(definition, scores[value]) for value in values)


def _decimal_values(array: pa.Array | pa.ChunkedArray) -> tuple[Decimal | None, ...]:
    if not pa.types.is_decimal(array.type):
        raise ValueError("Operator inputs must use Arrow Decimal")
    return tuple(array.to_pylist())


def _quantize(definition: OnlyCalculationDefinition, value: Decimal) -> Decimal:
    quantum = definition.numeric.output_quantum
    if quantum is None:
        raise ValueError("Operator requires output_quantum")
    with localcontext() as context:
        context.prec = definition.numeric.precision
        context.rounding = definition.numeric.rounding
        return value.quantize(quantum)
