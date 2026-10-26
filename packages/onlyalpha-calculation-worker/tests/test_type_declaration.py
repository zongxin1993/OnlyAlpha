from decimal import Decimal

import pytest

from onlyalpha.algorithm.type_declaration import type_declaration
from onlyalpha.calculation.definition import (
    OnlyCalculationDataType,
    OnlyCalculationKind,
    OnlyCalculationTypeDefinition,
    OnlyMissingValuePolicy,
    OnlyNumericDefinition,
    OnlyOutputDefinition,
    OnlyParameterDefinition,
    OnlyParameterSchema,
    OnlyParameterType,
    OnlyTimestampSemantic,
)


def sample(default: object = Decimal("2E+1")) -> OnlyCalculationTypeDefinition:
    return OnlyCalculationTypeDefinition(
        OnlyCalculationKind.INDICATOR,
        "example.indicator",
        "1",
        OnlyParameterSchema(
            (
                OnlyParameterDefinition(
                    "label",
                    OnlyParameterType.STRING,
                    required=False,
                    default=default,
                    enum_values=(Decimal("2.0"), 2, True, "2", "2E+1", "20"),
                ),
            )
        ),
        (),
        (OnlyOutputDefinition("value", OnlyCalculationDataType.DECIMAL, True),),
        OnlyMissingValuePolicy.FAIL,
        OnlyTimestampSemantic.EVENT_TIME,
        OnlyNumericDefinition(),
    )


def test_actual_type_exports_lossless_values_without_changing_public_descriptor():
    from onlyalpha_calculation_worker.contracts import decode, encode

    declaration = type_declaration(sample())
    # The actual private wire accepts plain JSON primitives, not StrEnum leaves.
    assert decode(encode(declaration)) == declaration
    assert declaration["schema_version"] == 1
    assert declaration["descriptor"]["parameters"][0]["default"] == "20"
    assert declaration["parameter_values"] == [
        {
            "default": {"type": "DECIMAL", "value": "2E+1"},
            "minimum": {"type": "NULL", "value": None},
            "maximum": {"type": "NULL", "value": None},
            "enum_values": [
                {"type": "DECIMAL", "value": "2.0"},
                {"type": "INTEGER", "value": 2},
                {"type": "BOOLEAN", "value": True},
                {"type": "STRING", "value": "2"},
                {"type": "STRING", "value": "2E+1"},
                {"type": "STRING", "value": "20"},
            ],
        }
    ]
    assert sample().parameters.normalize({})["label"] == "2E+1"
    assert sample(Decimal("20")).parameters.normalize({})["label"] == "20"
    # The public projection cannot distinguish these normalization semantics.
    assert type_declaration(sample(Decimal("20")))["descriptor"] == declaration["descriptor"]
    assert type_declaration(sample(Decimal("20"))) != declaration


def test_declaration_preserves_signed_zero_exponent_and_returns_detached_values():
    native = sample(Decimal("-0E-7"))
    first = type_declaration(native)
    assert first["parameter_values"][0]["default"] == {"type": "DECIMAL", "value": "-0E-7"}
    assert first["descriptor"]["parameters"][0]["default"] == "-0.0000000"
    first["descriptor"]["parameters"][0]["default"] = "changed"
    assert type_declaration(native)["descriptor"]["parameters"][0]["default"] == "-0.0000000"


@pytest.mark.parametrize("default", [float("nan"), 1.5, [], {}, Decimal("NaN"), Decimal("Infinity")])
def test_declaration_rejects_non_contract_or_nonfinite_scalars(default):
    with pytest.raises(ValueError, match="CALCULATION_TYPE_DECLARATION_INVALID"):
        type_declaration(sample(default))


@pytest.mark.parametrize("location", ["parameter-positive", "parameter-negative", "quantum", "aggregate"])
def test_decimal_projection_budget_is_checked_before_the_public_formatter(monkeypatch, location):
    from dataclasses import replace

    native = sample()
    if location == "quantum":
        native = replace(native, numeric=OnlyNumericDefinition(output_quantum=Decimal("1E-999999999")))
    elif location == "aggregate":
        field = replace(
            native.parameters.fields[0],
            default=Decimal("1E+60000"),
            enum_values=(Decimal("1E+60000"),) * 20,
        )
        native = replace(native, parameters=OnlyParameterSchema((field,)))
    else:
        native = sample(Decimal("1E+999999999" if location == "parameter-positive" else "1E-999999999"))

    def prohibited_formatter(_definition):
        # The pre-fix behavior would try a billion-byte expansion. Fault the
        # expander instead, preserving a safe deterministic RED reproduction.
        raise AssertionError("public formatter ran before the expansion budget")

    monkeypatch.setattr(OnlyCalculationTypeDefinition, "descriptor", prohibited_formatter)
    with pytest.raises(ValueError, match="CALCULATION_TYPE_DECLARATION_UNAVAILABLE"):
        type_declaration(native)


def test_positive_exponent_zero_requires_no_fixed_point_padding_budget():
    declaration = type_declaration(sample(Decimal("-0E+999999999")))
    assert declaration["descriptor"]["parameters"][0]["default"] == "-0"
    assert declaration["parameter_values"][0]["default"] == {"type": "DECIMAL", "value": "-0E+999999999"}
