"""Exact Decimal finite-column RESEARCH Operator backend."""

from collections.abc import Mapping

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.calculation import OnlyCalculationDefinition
from onlyalpha_plugin_operators.semantics import evaluate

_DECIMAL = pa.decimal128(38, 12)


class OnlyOfficialResearchOperatorBackend:
    def execute(
        self, definition: OnlyCalculationDefinition, inputs: Mapping[str, pa.Array | pa.ChunkedArray]
    ) -> Mapping[str, pa.Array]:
        if any(not pa.types.is_decimal(array.type) for array in inputs.values()):
            raise ValueError("Operator inputs must use Arrow Decimal")
        outputs = evaluate(definition, {name: tuple(array.to_pylist()) for name, array in inputs.items()})
        return {name: pa.array(values, type=_DECIMAL) for name, values in outputs.items()}


__all__ = ["OnlyOfficialResearchOperatorBackend"]
