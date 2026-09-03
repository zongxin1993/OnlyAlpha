from decimal import ROUND_DOWN, Decimal, localcontext

import pyarrow as pa
import pytest
from onlyalpha_plugin_indicators.registration import (
    B1_FINANCIAL_TYPES,
    OBV,
    ROC,
    STOCHASTIC,
    VWAP,
    WMA,
    OnlyFinancialIndicatorDefinitionResolver,
    registrations,
)

from onlyalpha.calculation import OnlyCalculationBackendKind, OnlyCalculationReference

_D = pa.decimal128(38, 12)


def _definition(type_definition, parameters):
    sources = {
        item.name: OnlyCalculationReference(None, item.name, f"bar.{item.name if item.name != 'price' else 'close'}")
        for item in type_definition.inputs
    }
    return OnlyFinancialIndicatorDefinitionResolver(type_definition).resolve(parameters, sources)


def _registration(type_definition, backend):
    return next(item for item in registrations() if item.type_definition is type_definition and item.backend is backend)


@pytest.mark.parametrize(
    ("type_definition", "parameters", "inputs", "expected"),
    (
        (
            WMA,
            {"period": 3},
            {"price": ["1", "2", "4", "8"]},
            {"value": [None, None, "2.833333333333", "5.666666666667"]},
        ),
        (
            ROC,
            {"period": 2},
            {"price": ["1", "2", "4", "0"]},
            {"roc": [None, None, "3.000000000000", "-1.000000000000"]},
        ),
        (
            VWAP,
            {"period": 2},
            {"price": ["1", "3", "9"], "volume": ["1", "3", "0"]},
            {"vwap": [None, "2.500000000000", "3.000000000000"]},
        ),
        (
            OBV,
            {},
            {"close": ["1", "2", "2", "1"], "volume": ["10", "20", "30", "40"]},
            {"obv": ["0E-12", "20.000000000000", "20.000000000000", "-20.000000000000"]},
        ),
        (
            STOCHASTIC,
            {"k_period": 3, "d_period": 2},
            {"high": ["2", "3", "4", "5"], "low": ["0", "1", "2", "3"], "close": ["1", "2", "3", "4"]},
            {"k": [None, None, "75.000000000000", "75.000000000000"], "d": [None, None, None, "75.000000000000"]},
        ),
    ),
)
def test_b1_financial_exact_research_trading_and_checkpoint(type_definition, parameters, inputs, expected) -> None:
    definition = _definition(type_definition, parameters)
    research_registration = _registration(type_definition, OnlyCalculationBackendKind.RESEARCH)
    arrays = {name: pa.array([Decimal(value) for value in values], type=_D) for name, values in inputs.items()}
    research = {
        name: values.to_pylist() for name, values in research_registration.provider.execute(definition, arrays).items()
    }
    trading_registration = _registration(type_definition, OnlyCalculationBackendKind.TRADING)
    uninterrupted = trading_registration.provider.create(definition, object())
    streamed = {name: [] for name in expected}
    rows = zip(*(inputs[name] for name in inputs), strict=True)
    for row in rows:
        result = uninterrupted.update({name: Decimal(value) for name, value in zip(inputs, row, strict=True)})
        for name in streamed:
            streamed[name].append(result[name])
    assert (
        research
        == streamed
        == {name: [None if value is None else Decimal(value) for value in values] for name, values in expected.items()}
    )
    split = max(1, len(next(iter(inputs.values()))) // 2)
    original = trading_registration.provider.create(definition, object())
    input_rows = [dict(zip(inputs, row, strict=True)) for row in zip(*(inputs[name] for name in inputs), strict=True)]
    for row in input_rows[:split]:
        original.update({name: Decimal(value) for name, value in row.items()})
    restored = trading_registration.provider.create(definition, object())
    restored.restore_checkpoint(original.capture_checkpoint())
    assert [original.update({name: Decimal(value) for name, value in row.items()}) for row in input_rows[split:]] == [
        restored.update({name: Decimal(value) for name, value in row.items()}) for row in input_rows[split:]
    ]


def test_b1_financial_catalog_contracts_are_explicit() -> None:
    actual = registrations()
    assert all(item.semantic_version == "1" for item in B1_FINANCIAL_TYPES)
    assert all(item.missing_values.value == "PROPAGATE" for item in B1_FINANCIAL_TYPES)
    assert {item.type_definition for item in actual if item.type_definition in B1_FINANCIAL_TYPES} == set(
        B1_FINANCIAL_TYPES
    )
    assert all(item.implementation_manifest is not None for item in actual)


def test_financial_results_ignore_caller_decimal_context() -> None:
    definition = _definition(WMA, {"period": 2})
    backend = _registration(WMA, OnlyCalculationBackendKind.RESEARCH).provider
    inputs = {"price": pa.array([Decimal("1.234567890123"), Decimal("9.876543210987")], type=_D)}
    expected = backend.execute(definition, inputs)["value"].to_pylist()
    with localcontext() as caller:
        caller.prec = 4
        caller.rounding = ROUND_DOWN
        assert backend.execute(definition, inputs)["value"].to_pylist() == expected


def test_obv_checkpoint_rejects_inconsistent_last_close() -> None:
    definition = _definition(OBV, {})
    backend = _registration(OBV, OnlyCalculationBackendKind.TRADING).provider.create(definition, object())
    backend.update({"close": Decimal("1"), "volume": Decimal("10")})
    payload = backend.capture_checkpoint()
    payload["last_close"] = "2"
    restored = _registration(OBV, OnlyCalculationBackendKind.TRADING).provider.create(definition, object())
    with pytest.raises(ValueError, match="last close differs"):
        restored.restore_checkpoint(payload)
