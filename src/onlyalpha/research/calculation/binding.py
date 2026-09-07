"""Exact Historical Bar Dataset source binding."""

from __future__ import annotations

from dataclasses import dataclass

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.calculation import (
    PREDICATE_OPERAND_SEMANTIC_TYPE,
    OnlyCalculationDataType,
    OnlyInputDefinition,
    OnlyOutputDefinition,
)
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.research.dataset.schema import OnlyResearchBarDatasetSchema

from .errors import OnlyResearchCalculationError


@dataclass(frozen=True, slots=True)
class OnlyResearchDatasetSourceContractV1:
    column: str
    data_type: OnlyCalculationDataType
    semantic_roles: frozenset[str]
    dimensions: tuple[str, ...] = ("TIME",)
    unit: str | None = None
    source_id: str = ""
    schema_version: int = 1

    def __post_init__(self) -> None:
        # Preserve the pre-V1 public positional constructor while giving the
        # formal bar-source contract its canonical identifier.
        if not self.source_id:
            object.__setattr__(self, "source_id", f"bar.{self.column}")
        if self.schema_version != 1 or any(character.isspace() for character in self.source_id):
            raise ValueError("RESEARCH_SOURCE_CONTRACT_INVALID")
        if not self.column or not self.semantic_roles or not self.dimensions:
            raise ValueError("RESEARCH_SOURCE_CONTRACT_INVALID")

    @property
    def source_contract_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {
                "domain": "onlyalpha.research.dataset-source-contract",
                "schema_version": self.schema_version,
                "source_id": self.source_id,
                "column": self.column,
                "data_type": self.data_type.value,
                "semantic_roles": sorted(self.semantic_roles),
                "dimensions": list(self.dimensions),
                "unit": self.unit,
            }
        )


# Compatibility name for producer-side callers; the authority itself is explicitly V1.
OnlyResearchDatasetSourceContract = OnlyResearchDatasetSourceContractV1


_SOURCES = {
    "bar.open": OnlyResearchDatasetSourceContractV1(
        "open", OnlyCalculationDataType.DECIMAL, frozenset({"NUMERIC_SERIES", "PRICE"}), source_id="bar.open"
    ),
    "bar.high": OnlyResearchDatasetSourceContractV1(
        "high", OnlyCalculationDataType.DECIMAL, frozenset({"NUMERIC_SERIES", "PRICE"}), source_id="bar.high"
    ),
    "bar.low": OnlyResearchDatasetSourceContractV1(
        "low", OnlyCalculationDataType.DECIMAL, frozenset({"NUMERIC_SERIES", "PRICE"}), source_id="bar.low"
    ),
    "bar.close": OnlyResearchDatasetSourceContractV1(
        "close", OnlyCalculationDataType.DECIMAL, frozenset({"NUMERIC_SERIES", "PRICE"}), source_id="bar.close"
    ),
    "bar.volume": OnlyResearchDatasetSourceContractV1(
        "volume", OnlyCalculationDataType.DECIMAL, frozenset({"NUMERIC_SERIES", "QUANTITY"}), source_id="bar.volume"
    ),
    "bar.quote_volume": OnlyResearchDatasetSourceContractV1(
        "quote_volume",
        OnlyCalculationDataType.DECIMAL,
        frozenset({"NUMERIC_SERIES", "QUANTITY"}),
        source_id="bar.quote_volume",
    ),
    "bar.turnover_amount": OnlyResearchDatasetSourceContractV1(
        "turnover_amount",
        OnlyCalculationDataType.DECIMAL,
        frozenset({"NUMERIC_SERIES", "MONEY"}),
        source_id="bar.turnover_amount",
    ),
    "bar.trade_count": OnlyResearchDatasetSourceContractV1(
        "trade_count",
        OnlyCalculationDataType.INTEGER,
        frozenset({"NUMERIC_SERIES", "COUNT"}),
        source_id="bar.trade_count",
    ),
    "bar.open_interest": OnlyResearchDatasetSourceContractV1(
        "open_interest",
        OnlyCalculationDataType.DECIMAL,
        frozenset({"NUMERIC_SERIES", "QUANTITY"}),
        source_id="bar.open_interest",
    ),
}


def only_research_dataset_source_contract(source: str) -> OnlyResearchDatasetSourceContract | None:
    """Return the single read-only semantic contract used by admission and execution."""

    return _SOURCES.get(source)


def only_research_dataset_source_contracts() -> tuple[tuple[str, OnlyResearchDatasetSourceContract], ...]:
    """Enumerate the canonical source contracts in stable source order."""

    return tuple((source, _SOURCES[source]) for source in sorted(_SOURCES))


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
    only_research_dataset_source_output(contract, expected, nullable=field.nullable)
    return table.column(contract.column)


def only_research_dataset_source_output(
    contract: OnlyResearchDatasetSourceContractV1,
    expected: OnlyInputDefinition,
    *,
    nullable: bool,
) -> OnlyOutputDefinition:
    """Project one authoritative Source role for one exact Calculation input."""

    if not isinstance(contract, OnlyResearchDatasetSourceContractV1):
        raise OnlyResearchCalculationError("RESEARCH_SOURCE_CONTRACT_INVALID", "source contract")
    if expected.data_type is not contract.data_type:
        raise OnlyResearchCalculationError("RESEARCH_INPUT_INCOMPATIBLE", f"{contract.source_id} data_type")
    if nullable and not expected.nullable:
        raise OnlyResearchCalculationError("RESEARCH_INPUT_INCOMPATIBLE", f"{contract.source_id} nullability")
    if expected.dimensions != contract.dimensions:
        raise OnlyResearchCalculationError("RESEARCH_INPUT_INCOMPATIBLE", f"{contract.source_id} dimensions")
    if (
        expected.semantic_type != PREDICATE_OPERAND_SEMANTIC_TYPE
        and expected.semantic_type not in contract.semantic_roles
    ):
        raise OnlyResearchCalculationError("RESEARCH_INPUT_INCOMPATIBLE", f"{contract.source_id} semantic_type")
    if expected.semantic_type != PREDICATE_OPERAND_SEMANTIC_TYPE and expected.unit != contract.unit:
        raise OnlyResearchCalculationError("RESEARCH_INPUT_INCOMPATIBLE", f"{contract.source_id} unit")
    semantic_type = (
        min(contract.semantic_roles)
        if expected.semantic_type == PREDICATE_OPERAND_SEMANTIC_TYPE
        else expected.semantic_type
    )
    return OnlyOutputDefinition(
        "value",
        contract.data_type,
        nullable,
        contract.dimensions,
        semantic_type,
        contract.unit,
    )


__all__ = [
    "OnlyResearchDatasetSourceContract",
    "OnlyResearchDatasetSourceContractV1",
    "only_bind_research_dataset_source",
    "only_research_dataset_source_contract",
    "only_research_dataset_source_contracts",
    "only_research_dataset_source_output",
]
