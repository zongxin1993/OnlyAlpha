"""Exact Decimal finite-column Forward Return RESEARCH backend."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, localcontext

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.calculation import OnlyCalculationDefinition, OnlyCalculationKind

_DECIMAL = pa.decimal128(38, 12)


class OnlyOfficialResearchTargetBackend:
    def execute(
        self,
        definition: OnlyCalculationDefinition,
        inputs: Mapping[str, pa.Array | pa.ChunkedArray],
    ) -> Mapping[str, pa.Array]:
        if (
            definition.kind is not OnlyCalculationKind.TARGET
            or definition.type_id != "onlyalpha.target.forward_return"
            or definition.semantic_version != "1"
        ):
            raise ValueError(f"unsupported official Target: {definition.type_id}@{definition.semantic_version}")
        if set(inputs) != {"entry_price", "exit_price"}:
            raise ValueError("Forward Return input names are invalid")
        entry = _prices(inputs["entry_price"], "entry_price")
        exit_ = _prices(inputs["exit_price"], "exit_price")
        if len(entry) != len(exit_):
            raise ValueError("Forward Return input lengths differ")
        entry_offset = _offset(definition, "entry_offset")
        exit_offset = _offset(definition, "exit_offset")
        if entry_offset < 0 or exit_offset <= entry_offset:
            raise ValueError("Forward Return offsets are invalid")
        values: list[Decimal | None] = []
        for index in range(len(entry)):
            entry_index = index + entry_offset
            exit_index = index + exit_offset
            if exit_index >= len(entry):
                values.append(None)
                continue
            denominator = entry[entry_index]
            numerator = exit_[exit_index]
            if denominator is None or numerator is None:
                raise ValueError("Forward Return price source contains null")
            if not denominator.is_finite() or not numerator.is_finite() or denominator <= 0 or numerator <= 0:
                raise ValueError("Forward Return prices must be finite and positive")
            with localcontext() as context:
                context.prec = definition.numeric.precision
                context.rounding = definition.numeric.rounding
                values.append(_quantize(definition, numerator / denominator - Decimal(1)))
        return {"target_value": pa.array(values, type=_DECIMAL)}


def _prices(array: pa.Array | pa.ChunkedArray, name: str) -> tuple[Decimal | None, ...]:
    if not pa.types.is_decimal(array.type):
        raise ValueError(f"{name} must use Arrow Decimal")
    return tuple(array.to_pylist())


def _offset(definition: OnlyCalculationDefinition, name: str) -> int:
    value = definition.parameters.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _quantize(definition: OnlyCalculationDefinition, value: Decimal) -> Decimal:
    quantum = definition.numeric.output_quantum
    if quantum is None:
        raise ValueError("Forward Return requires output_quantum")
    with localcontext() as context:
        context.prec = definition.numeric.precision
        context.rounding = definition.numeric.rounding
        return value.quantize(quantum)
