from __future__ import annotations

from dataclasses import replace

import pyarrow as pa
import pytest
from onlyalpha_plugin_indicators.registration import TYPES, resolve_definition

from onlyalpha.calculation import (
    OnlyCalculationBackendKind,
    OnlyCalculationBackendRegistration,
    OnlyCalculationDataType,
    OnlyCalculationRegistry,
    OnlyInputDefinition,
)
from onlyalpha.research.calculation import (
    OnlyResearchCalculationBackendResolver,
    OnlyResearchCalculationError,
    only_bind_research_dataset_source,
    only_research_calculation_fingerprint,
)
from onlyalpha.research.dataset.codec import only_bars_to_table
from onlyalpha.research.dataset.schema import RESEARCH_BAR_DATASET_SCHEMA_V1
from tests.research.calculation.support import bars


class _Backend:
    def execute(self, definition, inputs):
        return {}


def test_research_resolver_is_exact_and_never_falls_back_to_trading() -> None:
    registry = OnlyCalculationRegistry()
    type_definition = TYPES[0]
    registry.register(OnlyCalculationBackendRegistration(type_definition, OnlyCalculationBackendKind.TRADING, object()))
    resolver = OnlyResearchCalculationBackendResolver(registry)
    definition = resolve_definition(type_definition, {"period": 2})
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_BACKEND_UNAVAILABLE.*unsupported backend"):
        resolver.resolve(definition)
    registration = OnlyCalculationBackendRegistration(type_definition, OnlyCalculationBackendKind.RESEARCH, _Backend())
    registry.register(registration)
    assert resolver.resolve(definition) is registration.provider
    with pytest.raises(OnlyResearchCalculationError, match="unknown semantic version"):
        resolver.resolve(replace(definition, semantic_version="999"))
    unknown = replace(definition, type_id="vendor.indicator.unknown")
    with pytest.raises(OnlyResearchCalculationError, match="unknown calculation type"):
        resolver.resolve(unknown)
    invalid = OnlyCalculationRegistry()
    invalid.register(OnlyCalculationBackendRegistration(type_definition, OnlyCalculationBackendKind.RESEARCH, object()))
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_BACKEND_INVALID"):
        OnlyResearchCalculationBackendResolver(invalid).resolve(definition)


@pytest.mark.parametrize("source", ("bar.close", "bar.volume", "bar.high", "bar.low"))
def test_dataset_sources_bind_exact_columns(source: str) -> None:
    table = only_bars_to_table(bars())
    result = only_bind_research_dataset_source(
        source,
        OnlyInputDefinition("value", OnlyCalculationDataType.DECIMAL),
        table,
        RESEARCH_BAR_DATASET_SCHEMA_V1,
    )
    assert result.equals(table.column(source.split(".")[1]))


def test_dataset_source_binding_fails_closed_on_contract_mismatch() -> None:
    table = only_bars_to_table(bars())
    expected = OnlyInputDefinition("value", OnlyCalculationDataType.DECIMAL)
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_SOURCE_UNSUPPORTED"):
        only_bind_research_dataset_source("bar.unknown", expected, table, RESEARCH_BAR_DATASET_SCHEMA_V1)
    with pytest.raises(OnlyResearchCalculationError, match="data_type"):
        only_bind_research_dataset_source(
            "bar.close",
            replace(expected, data_type=OnlyCalculationDataType.INTEGER),
            table,
            RESEARCH_BAR_DATASET_SCHEMA_V1,
        )
    with pytest.raises(OnlyResearchCalculationError, match="semantic_type"):
        only_bind_research_dataset_source(
            "bar.close", replace(expected, semantic_type="COUNT"), table, RESEARCH_BAR_DATASET_SCHEMA_V1
        )
    with pytest.raises(OnlyResearchCalculationError, match="unit"):
        only_bind_research_dataset_source(
            "bar.close", replace(expected, unit="USD"), table, RESEARCH_BAR_DATASET_SCHEMA_V1
        )
    missing = table.drop(["close"])
    with pytest.raises(OnlyResearchCalculationError, match="missing column"):
        only_bind_research_dataset_source("bar.close", expected, missing, RESEARCH_BAR_DATASET_SCHEMA_V1)
    with pytest.raises(OnlyResearchCalculationError, match="nullability"):
        only_bind_research_dataset_source("bar.quote_volume", expected, table, RESEARCH_BAR_DATASET_SCHEMA_V1)


@pytest.mark.parametrize(
    "expected",
    (
        OnlyInputDefinition("value", OnlyCalculationDataType.DECIMAL, dimensions=("ASSET", "TIME")),
        OnlyInputDefinition("value", OnlyCalculationDataType.DECIMAL, dimensions=()),
    ),
)
def test_dataset_source_binding_rejects_unsupported_dimensions(expected: OnlyInputDefinition) -> None:
    with pytest.raises(OnlyResearchCalculationError) as raised:
        only_bind_research_dataset_source(
            "bar.close", expected, only_bars_to_table(bars()), RESEARCH_BAR_DATASET_SCHEMA_V1
        )
    assert raised.value.code == "RESEARCH_INPUT_INCOMPATIBLE"
    assert raised.value.detail == "bar.close dimensions"


@pytest.mark.parametrize(
    "field",
    (
        pa.field("close", pa.int64(), nullable=False),
        pa.field("close", pa.decimal128(38, 18), nullable=True),
    ),
    ids=("data-type", "field-nullability"),
)
def test_dataset_source_binding_rejects_wrong_arrow_field(field: pa.Field) -> None:
    table = only_bars_to_table(bars())
    index = table.schema.get_field_index("close")
    values = (
        pa.array(range(table.num_rows), type=pa.int64())
        if pa.types.is_integer(field.type)
        else table.column("close").combine_chunks()
    )
    incompatible = table.set_column(index, field, values)
    with pytest.raises(OnlyResearchCalculationError) as raised:
        only_bind_research_dataset_source(
            "bar.close",
            OnlyInputDefinition("value", OnlyCalculationDataType.DECIMAL),
            incompatible,
            RESEARCH_BAR_DATASET_SCHEMA_V1,
        )
    assert raised.value.code == "RESEARCH_INPUT_INCOMPATIBLE"
    assert raised.value.detail == "wrong Arrow field close"


def test_research_calculation_identity_contains_only_semantic_authorities() -> None:
    first = only_research_calculation_fingerprint("a" * 64, "b" * 64)
    assert first == only_research_calculation_fingerprint("a" * 64, "b" * 64)
    assert first != only_research_calculation_fingerprint("c" * 64, "b" * 64)
    assert len(first) == 64
