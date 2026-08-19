"""Exact Historical Bar Dataset source binding."""

from __future__ import annotations

from dataclasses import dataclass

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.calculation import PREDICATE_OPERAND_SEMANTIC_TYPE, OnlyCalculationDataType, OnlyInputDefinition
from onlyalpha.research.dataset.schema import OnlyResearchBarDatasetSchema

from .errors import OnlyResearchCalculationError


@dataclass(frozen=True, slots=True)
class OnlyResearchDatasetSourceContract:
    column: str
    data_type: OnlyCalculationDataType
    semantic_roles: frozenset[str]
    dimensions: tuple[str, ...] = ("TIME",)
    unit: str | None = None


_SOURCES = {
    "bar.open": OnlyResearchDatasetSourceContract(
        "open", OnlyCalculationDataType.DECIMAL, frozenset({"NUMERIC_SERIES", "PRICE"})
    ),
    "bar.high": OnlyResearchDatasetSourceContract(
        "high", OnlyCalculationDataType.DECIMAL, frozenset({"NUMERIC_SERIES", "PRICE"})
    ),
    "bar.low": OnlyResearchDatasetSourceContract(
        "low", OnlyCalculationDataType.DECIMAL, frozenset({"NUMERIC_SERIES", "PRICE"})
    ),
    "bar.close": OnlyResearchDatasetSourceContract(
        "close", OnlyCalculationDataType.DECIMAL, frozenset({"NUMERIC_SERIES", "PRICE"})
    ),
    "bar.volume": OnlyResearchDatasetSourceContract(
        "volume", OnlyCalculationDataType.DECIMAL, frozenset({"NUMERIC_SERIES", "QUANTITY"})
    ),
    "bar.quote_volume": OnlyResearchDatasetSourceContract(
        "quote_volume", OnlyCalculationDataType.DECIMAL, frozenset({"NUMERIC_SERIES", "QUANTITY"})
    ),
    "bar.turnover_amount": OnlyResearchDatasetSourceContract(
        "turnover_amount", OnlyCalculationDataType.DECIMAL, frozenset({"NUMERIC_SERIES", "MONEY"})
    ),
    "bar.trade_count": OnlyResearchDatasetSourceContract(
        "trade_count", OnlyCalculationDataType.INTEGER, frozenset({"NUMERIC_SERIES", "COUNT"})
    ),
    "bar.open_interest": OnlyResearchDatasetSourceContract(
        "open_interest", OnlyCalculationDataType.DECIMAL, frozenset({"NUMERIC_SERIES", "QUANTITY"})
    ),
}


def only_research_dataset_source_contract(source: str) -> OnlyResearchDatasetSourceContract | None:
    """Return the single read-only semantic contract used by admission and execution."""

    return _SOURCES.get(source)


def only_bind_research_dataset_source(
    source: str,
    expected: OnlyInputDefinition,
    table: pa.Table,
    schema: OnlyResearchBarDatasetSchema,
) -> pa.ChunkedArray:
    contract = only_research_dataset_source_contract(source)
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
    if expected.dimensions != contract.dimensions:
        raise OnlyResearchCalculationError("RESEARCH_INPUT_INCOMPATIBLE", f"{source} dimensions")
    if (
        expected.semantic_type != PREDICATE_OPERAND_SEMANTIC_TYPE
        and expected.semantic_type not in contract.semantic_roles
    ):
        raise OnlyResearchCalculationError("RESEARCH_INPUT_INCOMPATIBLE", f"{source} semantic_type")
    if expected.semantic_type != PREDICATE_OPERAND_SEMANTIC_TYPE and expected.unit != contract.unit:
        raise OnlyResearchCalculationError("RESEARCH_INPUT_INCOMPATIBLE", f"{source} unit")
    return table.column(contract.column)


__all__ = [
    "OnlyResearchDatasetSourceContract",
    "only_bind_research_dataset_source",
    "only_research_dataset_source_contract",
]
