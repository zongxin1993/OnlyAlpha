"""Structural output validation shared by publishing and disposable SPI consumers."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.calculation.definition import (
    FACTOR_SCORE_SEMANTIC_TYPE,
    OnlyCalculationDataType,
    OnlyCalculationDefinition,
    OnlyOutputDefinition,
    only_calculation_semantic_bounds,
)
from onlyalpha.research.calculation.errors import OnlyResearchCalculationError


def only_validate_research_outputs(
    definition: OnlyCalculationDefinition,
    raw: Mapping[str, pa.Array | pa.ChunkedArray],
    row_count: int,
) -> Mapping[str, pa.Array | pa.ChunkedArray]:
    expected = {item.name: item for item in definition.outputs}
    if not isinstance(raw, Mapping) or set(raw) != set(expected):
        raise OnlyResearchCalculationError("RESEARCH_OUTPUT_INVALID", "output names")
    result: dict[str, pa.Array | pa.ChunkedArray] = {}
    for name in sorted(expected):
        value = raw[name]
        if not isinstance(value, (pa.Array, pa.ChunkedArray)) or len(value) != row_count:
            raise OnlyResearchCalculationError("RESEARCH_OUTPUT_INVALID", f"{name} row count")
        contract = expected[name]
        if not _output_type_matches(value.type, contract):
            raise OnlyResearchCalculationError("RESEARCH_OUTPUT_INVALID", f"{name} data_type")
        if value.null_count and not contract.nullable:
            raise OnlyResearchCalculationError("RESEARCH_OUTPUT_INVALID", f"{name} nullability")
        bounds = only_calculation_semantic_bounds(contract.semantic_type)
        if contract.semantic_type == FACTOR_SCORE_SEMANTIC_TYPE and bounds is not None:
            values = value.to_pylist()
            if any(item is not None and not bounds[0] <= item <= bounds[1] for item in values):
                raise OnlyResearchCalculationError("RESEARCH_SCORE_OUT_OF_RANGE", name)
        result[name] = value
    return MappingProxyType(result)


def _output_type_matches(data_type: pa.DataType, contract: OnlyOutputDefinition) -> bool:
    return (
        contract.data_type is OnlyCalculationDataType.DECIMAL
        and pa.types.is_decimal(data_type)
        or contract.data_type is OnlyCalculationDataType.INTEGER
        and pa.types.is_integer(data_type)
        or contract.data_type is OnlyCalculationDataType.BOOLEAN
        and pa.types.is_boolean(data_type)
        or contract.data_type is OnlyCalculationDataType.STRING
        and pa.types.is_string(data_type)
    )
