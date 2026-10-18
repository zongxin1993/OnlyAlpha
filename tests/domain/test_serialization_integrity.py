"""Domain decoding preserves financial inputs and concrete instrument semantics."""

from copy import deepcopy

import pytest

from onlyalpha.domain.catalog import OnlyInstrumentCatalog
from onlyalpha.domain.errors import OnlySerializationError, OnlyValidationError
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlySymbol, OnlyVenueId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.value import OnlyPrice
from tests.domain.conformance.support.instruments import build_instruments


def test_catalog_restores_concrete_instrument_types_and_fields() -> None:
    catalog = OnlyInstrumentCatalog(tuple(build_instruments().values()))
    restored = OnlyInstrumentCatalog.from_json(catalog.to_json())
    assert restored == catalog
    assert [type(item) for item in restored.instruments] == [type(item) for item in catalog.instruments]


@pytest.mark.parametrize("invalid", [1.25, 1, True, None, "NaN", "Infinity"])
def test_financial_wire_values_require_finite_decimal_strings(invalid: object) -> None:
    with pytest.raises(OnlySerializationError):
        OnlyPrice.from_dict({"schema_version": 1, "value": invalid, "precision": 2})


def test_fixed_discriminants_and_unknown_fields_are_checked(equity) -> None:
    invalid = deepcopy(equity.to_dict())
    invalid["asset_class"] = "FUND"
    with pytest.raises(OnlySerializationError):
        type(equity).from_dict(invalid)
    invalid = deepcopy(equity.to_dict())
    invalid["unexpected"] = "silently lost"
    with pytest.raises(OnlySerializationError):
        type(equity).from_dict(invalid)


def test_identifier_encoding_is_injective_and_preserves_symbol_dots() -> None:
    identifier = OnlyInstrumentId(OnlySymbol("BRK.B"), OnlyVenueId("XNAS"))
    assert OnlyInstrumentId.parse(str(identifier)) == identifier
    with pytest.raises(OnlyValidationError):
        OnlyVenueId("B.C")


def test_base_instrument_cannot_silently_discard_derivative_fields() -> None:
    future = next(item for item in build_instruments().values() if hasattr(item, "expiration_time"))
    restored = OnlyInstrument.from_dict(future.to_dict())
    assert type(restored) is type(future)
    assert restored == future


@pytest.mark.parametrize("tag", ["OnlyOption", "unknown", None])
def test_instrument_type_tags_cannot_be_substituted(equity, tag: object) -> None:
    payload = equity.to_dict()
    payload["model_type"] = tag
    with pytest.raises(OnlySerializationError):
        type(equity).from_dict(payload)


def test_generic_instrument_remains_an_explicit_variant(equity) -> None:
    payload = equity.to_dict()
    payload["model_type"] = "OnlyInstrument"
    restored = OnlyInstrument.from_dict(payload)
    assert type(restored) is OnlyInstrument
    assert restored.to_dict() == payload


def test_boolean_schema_is_not_an_integer_version() -> None:
    with pytest.raises(OnlySerializationError):
        OnlyPrice.from_dict({"schema_version": True, "value": "1.25", "precision": 2})


@pytest.mark.parametrize("invalid", [True, 1.5, "1", None])
def test_timestamp_constructor_and_unit_factories_require_integers(invalid: object) -> None:
    from onlyalpha.domain.time import OnlyTimestamp

    for constructor in (
        OnlyTimestamp,
        OnlyTimestamp.from_unix_seconds,
        OnlyTimestamp.from_unix_millis,
        OnlyTimestamp.from_unix_micros,
        OnlyTimestamp.from_unix_nanos,
    ):
        with pytest.raises(OnlyValidationError):
            constructor(invalid)


def test_timestamp_datetime_ingress_requires_explicit_conversion() -> None:
    from datetime import UTC, datetime

    from onlyalpha.domain.time import OnlyTimestamp

    instant = datetime(2025, 7, 1, tzinfo=UTC)
    with pytest.raises(OnlyValidationError):
        OnlyTimestamp(instant)
    assert OnlyTimestamp.from_datetime(instant).to_datetime() == instant


@pytest.mark.parametrize("invalid", ["NaN", "Infinity", "-Infinity", 1.25, True])
def test_bar_thresholds_reject_nonfinite_and_inexact_values(invalid: object) -> None:
    from onlyalpha.domain.market import OnlyValueBarFormation, OnlyVolumeBarFormation

    for constructor in (OnlyValueBarFormation, OnlyVolumeBarFormation):
        with pytest.raises(OnlyValidationError):
            constructor(invalid)


@pytest.mark.parametrize("version", [3.0, True, "3"])
def test_bar_semantic_rejects_non_integer_schema(version) -> None:
    from onlyalpha.domain.market import OnlyBarSemantic

    record = OnlyBarSemantic.fixed_duration(1).to_dict()
    record["schema_version"] = version
    with pytest.raises(OnlyValidationError):
        OnlyBarSemantic.from_dict(record)


@pytest.mark.parametrize("version", [1.0, True, "1"])
def test_trade_semantic_and_input_reject_non_integer_schema(version) -> None:
    from onlyalpha.domain.market import OnlyTradeInputType, OnlyTradeSemantic

    with pytest.raises(OnlyValidationError):
        OnlyTradeSemantic.from_dict({"schema_version": version, "kind": "TRADE"})
    record = OnlyTradeInputType(OnlyInstrumentId.parse("A.X")).to_dict()
    record["schema_version"] = version
    with pytest.raises(OnlyValidationError):
        OnlyTradeInputType.from_dict(record)
