from dataclasses import replace
from decimal import Decimal

import pyarrow as pa
import pytest
from onlyalpha_plugin_operators.registration import (
    CROSS_SECTION_PERCENTILE,
    P0_TYPES,
    ROLLING_MEAN,
    registrations,
    resolve_cross_section_percentile,
    resolve_rolling_mean,
)
from onlyalpha_plugin_operators.research import OnlyOfficialResearchOperatorBackend
from onlyalpha_plugin_operators.trading import OnlyOfficialTradingOperatorBackendFactory

from onlyalpha.calculation import (
    CALCULATION_EXECUTION_SHAPE_EXTENSION,
    OnlyCalculationBackendKind,
    OnlyCalculationKind,
    OnlyCalculationReference,
    OnlyFactorKind,
    only_calculation_execution_shape,
)

_D = pa.decimal128(38, 12)


def _source() -> OnlyCalculationReference:
    return OnlyCalculationReference(None, "value", "dataset.value")


def test_l1_definitions_are_generic_non_factor_calculations() -> None:
    assert ROLLING_MEAN.kind is CROSS_SECTION_PERCENTILE.kind is OnlyCalculationKind.INDICATOR
    assert ROLLING_MEAN.type_id == "onlyalpha.operator.rolling_mean"
    assert CROSS_SECTION_PERCENTILE.type_id == "onlyalpha.operator.cross_section_percentile"
    assert all(item.factor_kind is None for item in (ROLLING_MEAN, CROSS_SECTION_PERCENTILE))
    percentile = resolve_cross_section_percentile({}, _source())
    assert percentile.inputs[0].semantic_type == percentile.outputs[0].semantic_type == "NUMERIC_SERIES"
    assert percentile.extensions == {CALCULATION_EXECUTION_SHAPE_EXTENSION: "CROSS_SECTION"}
    assert type(percentile).from_dict(percentile.to_dict()) == percentile
    assert only_calculation_execution_shape(percentile) is OnlyFactorKind.CROSS_SECTION


def test_pre_b1_l1_definition_identities_are_exactly_preserved() -> None:
    rolling_one = resolve_rolling_mean({"period": 1}, _source())
    rolling_three = resolve_rolling_mean({"period": 3}, _source())
    percentile = resolve_cross_section_percentile({}, _source())
    lower_percentile = resolve_cross_section_percentile({"direction": "LOWER_IS_BETTER"}, _source())

    assert rolling_one.warmup.ready_condition == "declared input is available"
    assert rolling_one.fingerprint == "c315536669add8a901d02051597219a4dff7e9cb5448c8b2a6ea676cb40aad7c"
    assert rolling_three.warmup.ready_condition == "complete declared input window is available"
    assert rolling_three.fingerprint == "c8090848926bea5073fa564ab35395b2a1e353adde7f85920cf200a08d8faa76"
    assert percentile.warmup.ready_condition == "declared input is available"
    assert percentile.fingerprint == "9259f6b3d79ef6c801996c5ffc5bcef7fdb07f52a37948d00fa1385948c3fa0d"
    assert lower_percentile.fingerprint == "2fe30b38133d189fceaf88947d9feae72c7bc025be0253e2eeb42ec787da596e"


def test_rolling_mean_has_explicit_warmup_null_and_decimal_semantics() -> None:
    definition = resolve_rolling_mean({"period": 3}, _source())
    assert definition.warmup.minimum_observations == 3
    assert definition.numeric.precision == 28
    backend = OnlyOfficialResearchOperatorBackend()
    result = backend.execute(
        definition,
        {"value": pa.array([Decimal("1"), Decimal("2"), Decimal("3"), None, Decimal("5")], type=_D)},
    )["value"].to_pylist()
    assert result == [None, None, Decimal("2.000000000000"), None, None]


def test_cross_section_percentile_is_stable_with_ties_nulls_and_direction() -> None:
    backend = OnlyOfficialResearchOperatorBackend()
    values = {"value": pa.array([Decimal("5"), None, Decimal("1"), Decimal("5")], type=_D)}
    higher = backend.execute(resolve_cross_section_percentile({}, _source()), values)["percentile"].to_pylist()
    lower = backend.execute(resolve_cross_section_percentile({"direction": "lower_is_better"}, _source()), values)[
        "percentile"
    ].to_pylist()
    assert higher == [Decimal("0.750000000000"), None, Decimal("0E-12"), Decimal("0.750000000000")]
    assert lower == [Decimal("0.250000000000"), None, Decimal("1.000000000000"), Decimal("0.250000000000")]
    assert all(value is None or Decimal(0) <= value <= Decimal(1) for value in (*higher, *lower))


def test_rolling_mean_trading_checkpoint_continuation_is_exact() -> None:
    definition = resolve_rolling_mean({"period": 2}, _source())
    factory = OnlyOfficialTradingOperatorBackendFactory()
    original = factory.create(definition, object())
    assert original.update({"value": Decimal("1")}) == {"value": None}
    checkpoint = original.capture_checkpoint()
    restored = factory.create(definition, object())
    restored.restore_checkpoint(checkpoint)
    assert (
        original.update({"value": Decimal("3")})
        == restored.update({"value": Decimal("3")})
        == {"value": Decimal("2.000000000000")}
    )
    with pytest.raises(ValueError, match="inputs"):
        restored.restore_checkpoint({"wrong": []})


def test_operator_registrations_have_exact_manifests_and_capabilities() -> None:
    actual = registrations()
    assert {item.type_definition for item in actual} == set(P0_TYPES)
    assert {item.backend for item in actual} == {
        OnlyCalculationBackendKind.RESEARCH,
        OnlyCalculationBackendKind.TRADING,
    }
    assert all(item.implementation_manifest is not None for item in actual)
    rolling_trading = next(
        item
        for item in actual
        if item.type_definition is ROLLING_MEAN and item.backend is OnlyCalculationBackendKind.TRADING
    )
    assert rolling_trading.checkpoint_schema_version == 2
    assert (
        OnlyOfficialTradingOperatorBackendFactory()
        .create(resolve_rolling_mean({"period": 2}, _source()), object())
        .checkpoint_schema_version
        == 2
    )
    with pytest.raises(ValueError, match="unsupported"):
        OnlyOfficialTradingOperatorBackendFactory().create(
            replace(resolve_rolling_mean({"period": 2}, _source()), type_id="vendor.operator"), object()
        )
