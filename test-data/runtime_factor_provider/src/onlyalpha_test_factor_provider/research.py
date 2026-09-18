"""Exact Decimal RESEARCH backend for the example Momentum hypothesis."""

from collections.abc import Mapping
from decimal import Decimal, localcontext

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.calculation import OnlyCalculationDefinition

_DECIMAL = pa.decimal128(38, 12)


class OnlyExampleResearchMomentumBackend:
    def execute(
        self,
        definition: OnlyCalculationDefinition,
        inputs: Mapping[str, pa.Array | pa.ChunkedArray],
    ) -> Mapping[str, pa.Array]:
        if definition.type_id != "example.factor.momentum" or definition.semantic_version != "1":
            raise ValueError(f"unsupported example Factor: {definition.type_id}@{definition.semantic_version}")
        if set(inputs) != {"return_short", "return_long"}:
            raise ValueError("Momentum input names are invalid")
        short = _decimals(inputs["return_short"])
        long = _decimals(inputs["return_long"])
        if len(short) != len(long):
            raise ValueError("Momentum input lengths differ")
        short_weight = _parameter(definition, "short_weight")
        long_weight = _parameter(definition, "long_weight")
        values = (
            None if left is None or right is None else _quantize(definition, short_weight * left + long_weight * right)
            for left, right in zip(short, long, strict=True)
        )
        return {"factor_value": pa.array(tuple(values), type=_DECIMAL)}


def _decimals(array: pa.Array | pa.ChunkedArray) -> tuple[Decimal | None, ...]:
    if not pa.types.is_decimal(array.type):
        raise ValueError("Momentum inputs must use Arrow Decimal")
    return tuple(array.to_pylist())


def _parameter(definition: OnlyCalculationDefinition, name: str) -> Decimal:
    value = definition.parameters[name]
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal")
    return value


def _quantize(definition: OnlyCalculationDefinition, value: Decimal) -> Decimal:
    quantum = definition.numeric.output_quantum
    if quantum is None:
        raise ValueError("Momentum requires output_quantum")
    with localcontext() as context:
        context.prec = definition.numeric.precision
        context.rounding = definition.numeric.rounding
        return value.quantize(quantum)
