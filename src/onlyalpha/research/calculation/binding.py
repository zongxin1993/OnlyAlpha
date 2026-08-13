"""Exact Historical Bar Dataset source binding."""

from __future__ import annotations

from dataclasses import dataclass

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.calculation import OnlyCalculationDataType, OnlyInputDefinition
from onlyalpha.research.dataset.schema import OnlyResearchBarDatasetSchema

from .errors import OnlyResearchCalculationError


@dataclass(frozen=True, slots=True)
class _SourceContract:
    column: str
    data_type: OnlyCalculationDataType
    semantic_roles: frozenset[str]


_SOURCES = {
    "bar.open": _SourceContract("open", OnlyCalculationDataType.DECIMAL, frozenset({"NUMERIC_SERIES", "PRICE"})),
    "bar.high": _SourceContract("high", OnlyCalculationDataType.DECIMAL, frozenset({"NUMERIC_SERIES", "PRICE"})),
    "bar.low": _SourceContract("low", OnlyCalculationDataType.DECIMAL, frozenset({"NUMERIC_SERIES", "PRICE"})),
    "bar.close": _SourceContract("close", OnlyCalculationDataType.DECIMAL, frozenset({"NUMERIC_SERIES", "PRICE"})),
    "bar.volume": _SourceContract("volume", OnlyCalculationDataType.DECIMAL, frozenset({"NUMERIC_SERIES", "QUANTITY"})),
    "bar.quote_volume": _SourceContract(
        "quote_volume", OnlyCalculationDataType.DECIMAL, frozenset({"NUMERIC_SERIES", "QUANTITY"})
    ),
    "bar.turnover_amount": _SourceContract(
        "turnover_amount", OnlyCalculationDataType.DECIMAL, frozenset({"NUMERIC_SERIES", "MONEY"})
    ),
    "bar.trade_count": _SourceContract(
        "trade_count", OnlyCalculationDataType.INTEGER, frozenset({"NUMERIC_SERIES", "COUNT"})
    ),
    "bar.open_interest": _SourceContract(
        "open_interest", OnlyCalculationDataType.DECIMAL, frozenset({"NUMERIC_SERIES", "QUANTITY"})
    ),
}


def only_bind_research_dataset_source(
    source: str,
    expected: OnlyInputDefinition,
    table: pa.Table,
    schema: OnlyResearchBarDatasetSchema,
) -> pa.ChunkedArray:
    contract = _SOURCES.get(source)
    if contract is None:
        raise OnlyResearchCalculationError("RESEARCH_SOURCE_UNSUPPORTED", source)
    field = schema.arrow_schema.field(contract.column)
    if table.schema.get_field_index(contract.column) < 0:
        raise OnlyResearchCalculationError("RESEARCH_INPUT_INCOMPATIBLE", f"missing column {contract.column}")
    if table.schema.field(contract.column) != field:
        raise OnlyResearchCalculationError("RESEARCH_INPUT_INCOMPATIBLE", f"wrong Arrow field {contract.column}")
    if expected.data_type is not contract.data_type:
        raise OnlyResearchCalculationError("RESEARCH_INPUT_INCOMPATIBLE", f"{source} data_type")
    if field.nullable and not expected.nullable:
        raise OnlyResearchCalculationError("RESEARCH_INPUT_INCOMPATIBLE", f"{source} nullability")
    if expected.dimensions != ("TIME",):
        raise OnlyResearchCalculationError("RESEARCH_INPUT_INCOMPATIBLE", f"{source} dimensions")
    if expected.semantic_type not in contract.semantic_roles:
        raise OnlyResearchCalculationError("RESEARCH_INPUT_INCOMPATIBLE", f"{source} semantic_type")
    if expected.unit is not None:
        raise OnlyResearchCalculationError("RESEARCH_INPUT_INCOMPATIBLE", f"{source} unit")
    return table.column(contract.column)
