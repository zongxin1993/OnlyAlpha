from decimal import Decimal

import pytest
from onlyalpha_plugin_factors.registration import registrations as factor_registrations
from onlyalpha_plugin_indicators.registration import TYPES, resolve_definition
from onlyalpha_plugin_indicators.registration import registrations as indicator_registrations

from onlyalpha.calculation import (
    OnlyCalculationKind,
    OnlyCalculationReference,
    OnlyCalculationRegistry,
    OnlyCalculationTypeReference,
)


def _registry() -> OnlyCalculationRegistry:
    result = OnlyCalculationRegistry()
    for registration in (*indicator_registrations(), *factor_registrations()):
        result.register(registration)
    return result


def _reference(kind: OnlyCalculationKind, type_id: str, version: str = "1") -> OnlyCalculationTypeReference:
    return OnlyCalculationTypeReference(kind, type_id, version)


def test_backend_neutral_resolver_rebuilds_indicator_parameter_derived_semantics() -> None:
    registry = _registry()
    ema = next(item for item in TYPES if item.type_id.endswith(".ema"))
    reference = _reference(OnlyCalculationKind.INDICATOR, ema.type_id)
    short = registry.rematerialize_definition(reference, {"period": 5}, {})
    long = registry.rematerialize_definition(reference, {"period": 20}, {})
    volume = registry.rematerialize_definition(reference, {"period": 5, "price_field": "volume"}, {})
    assert short.warmup.minimum_observations == 5
    assert long.warmup.minimum_observations == 20
    assert volume.input_bindings["value"].source == "bar.volume"
    assert len({short.fingerprint, long.fingerprint, volume.fingerprint}) == 3
    baseline = resolve_definition(ema, {"period": 5})
    assert short == baseline
    assert short.fingerprint == baseline.fingerprint


def test_macd_cross_parameter_validation_and_default_warmup_are_reapplied() -> None:
    registry = _registry()
    macd = next(item for item in TYPES if item.type_id.endswith(".macd"))
    reference = _reference(OnlyCalculationKind.INDICATOR, macd.type_id)
    resolved = registry.rematerialize_definition(
        reference, {"fast_period": 3, "slow_period": 8, "signal_period": 2}, {}
    )
    assert resolved.parameters["warmup_bars"] == 9
    assert resolved.warmup.minimum_observations == 9
    with pytest.raises(ValueError, match="fast_period"):
        registry.rematerialize_definition(reference, {"fast_period": 8, "slow_period": 3, "signal_period": 2}, {})


def test_factor_resolution_uses_exact_composition_bindings_and_normalization() -> None:
    registry = _registry()
    left = OnlyCalculationReference("a" * 64, "value")
    right = OnlyCalculationReference("b" * 64, "value")
    momentum = registry.rematerialize_definition(
        _reference(OnlyCalculationKind.FACTOR, "onlyalpha.factor.momentum"),
        {"short_weight": "0.25", "long_weight": Decimal("0.75")},
        {"return_short": left, "return_long": right},
    )
    percentile = registry.rematerialize_definition(
        _reference(OnlyCalculationKind.FACTOR, "onlyalpha.factor.cross_section_percentile"),
        {"direction": "lower_is_better"},
        {"factor_value": OnlyCalculationReference(momentum.fingerprint, "factor_value")},
    )
    assert momentum.parameters == {"short_weight": Decimal("0.25"), "long_weight": Decimal("0.75")}
    assert percentile.parameters["direction"] == "LOWER_IS_BETTER"
    assert not hasattr(momentum, "resolver_fingerprint")
    assert "OnlyOfficial" not in str(momentum.semantic_payload())


def test_rematerialization_is_exact_and_fails_closed_without_a_registered_resolver() -> None:
    registry = OnlyCalculationRegistry()
    registration = indicator_registrations()[0]
    registry.register(type(registration)(registration.type_definition, registration.backend, registration.provider))
    reference = _reference(
        registration.type_definition.kind,
        registration.type_definition.type_id,
        registration.type_definition.semantic_version,
    )
    with pytest.raises(ValueError, match="resolver is unavailable"):
        registry.rematerialize_definition(reference, {}, {})
    with pytest.raises(ValueError, match="unknown semantic version"):
        registry.resolve_type(
            _reference(registration.type_definition.kind, registration.type_definition.type_id, "future")
        )
