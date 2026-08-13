"""Exact columnar schema authority for Historical Closed Bar Dataset v1."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.canonical import only_canonical_fingerprint


@dataclass(frozen=True, slots=True)
class OnlyResearchDatasetColumn:
    name: str
    logical_type: str
    nullable: bool
    semantic_role: str


@dataclass(frozen=True, slots=True)
class OnlyResearchBarDatasetSchema:
    schema_id: str = "onlyalpha.research.historical_bar"
    schema_version: int = 1

    @property
    def columns(self) -> tuple[OnlyResearchDatasetColumn, ...]:
        return _COLUMNS

    def semantic_payload(self) -> Mapping[str, object]:
        return {
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "columns": [
                {
                    "name": item.name,
                    "logical_type": item.logical_type,
                    "nullable": item.nullable,
                    "semantic_role": item.semantic_role,
                }
                for item in self.columns
            ],
        }

    @property
    def fingerprint(self) -> str:
        return only_canonical_fingerprint(self.semantic_payload())

    @property
    def arrow_schema(self) -> pa.Schema:
        decimal = pa.decimal128(38, 18)
        types: dict[str, pa.DataType] = {
            "utf8": pa.string(),
            "int64": pa.int64(),
            "int32": pa.int32(),
            "bool": pa.bool_(),
            "date32": pa.date32(),
            "decimal128(38,18)": decimal,
        }
        return pa.schema([pa.field(item.name, types[item.logical_type], item.nullable) for item in self.columns])


_COLUMNS = tuple(
    OnlyResearchDatasetColumn(*item)
    for item in (
        ("instrument_id", "utf8", False, "instrument_identity"),
        ("bar_step", "int32", False, "bar_specification"),
        ("bar_aggregation", "utf8", False, "bar_specification"),
        ("price_type", "utf8", False, "bar_specification"),
        ("aggregation_source", "utf8", False, "bar_specification"),
        ("bar_start_ns", "int64", False, "utc_timestamp"),
        ("bar_end_ns", "int64", False, "utc_timestamp"),
        ("ts_event_ns", "int64", False, "utc_timestamp"),
        ("ts_init_ns", "int64", False, "utc_timestamp"),
        ("trading_day", "date32", False, "trading_day"),
        ("session_type", "utf8", False, "session"),
        ("open", "decimal128(38,18)", False, "price"),
        ("high", "decimal128(38,18)", False, "price"),
        ("low", "decimal128(38,18)", False, "price"),
        ("close", "decimal128(38,18)", False, "price"),
        ("price_precision", "int32", False, "precision"),
        ("volume", "decimal128(38,18)", False, "quantity"),
        ("volume_precision", "int32", False, "precision"),
        ("quote_volume", "decimal128(38,18)", True, "quantity"),
        ("quote_volume_precision", "int32", True, "precision"),
        ("turnover_amount", "decimal128(38,18)", True, "money"),
        ("turnover_currency", "utf8", True, "currency"),
        ("turnover_currency_precision", "int32", True, "precision"),
        ("turnover_currency_type", "utf8", True, "currency_type"),
        ("trade_count", "int64", True, "count"),
        ("open_interest", "decimal128(38,18)", True, "quantity"),
        ("open_interest_precision", "int32", True, "precision"),
        ("is_closed", "bool", False, "lifecycle"),
        ("revision", "int64", False, "revision"),
        ("adjustment_type", "utf8", False, "adjustment"),
    )
)


RESEARCH_BAR_DATASET_SCHEMA_V1 = OnlyResearchBarDatasetSchema()
