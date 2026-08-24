from dataclasses import replace
from decimal import Decimal

import pyarrow as pa
import pytest
from onlyalpha_plugin_factors.registration import (
    CROSS_SECTION_PERCENTILE,
    MOMENTUM,
    registrations,
    resolve_momentum,
    resolve_percentile,
)
from onlyalpha_plugin_factors.research import OnlyOfficialResearchFactorBackend

from onlyalpha.calculation import (
    FACTOR_SCORE_SEMANTIC_TYPE,
    FACTOR_VALUE_SEMANTIC_TYPE,
    OnlyCalculationBackendKind,
    OnlyCalculationKind,
    OnlyCalculationReference,
    OnlyCalculationRegistry,
    OnlyCalculationTypeReference,
    OnlyFactorKind,
    only_calculation_semantic_bounds,
)

_D = pa.decimal128(38, 12)


def _reference(seed: str, output: str) -> OnlyCalculationReference:
    return OnlyCalculationReference(seed * 64, output)


def _momentum(parameters=None):
    return resolve_momentum(parameters or {}, _reference("a", "value"), _reference("b", "value"))


def _percentile(parameters=None):
    return resolve_percentile(parameters or {}, _reference("c", "factor_value"))


def _factor_registry() -> OnlyCalculationRegistry:
    registry = OnlyCalculationRegistry()
    for registration in registrations():
        registry.register(registration)
    return registry


def _type_reference(type_definition) -> OnlyCalculationTypeReference:
    return OnlyCalculationTypeReference(
        type_definition.kind,
        type_definition.type_id,
        type_definition.semantic_version,
    )


def _assert_complete_definition_semantics_equal(direct, rematerialized) -> None:
    assert direct == rematerialized
    assert direct.kind is rematerialized.kind
    assert direct.type_id == rematerialized.type_id
    assert direct.semantic_version == rematerialized.semantic_version
    assert direct.parameters == rematerialized.parameters
    assert direct.input_bindings == rematerialized.input_bindings
    assert direct.inputs == rematerialized.inputs
    assert direct.outputs == rematerialized.outputs
    assert direct.warmup == rematerialized.warmup
    assert direct.missing_values is rematerialized.missing_values
    assert direct.timestamp is rematerialized.timestamp
    assert direct.numeric == rematerialized.numeric
    assert direct.factor_kind is rematerialized.factor_kind
    assert direct.extensions == rematerialized.extensions
    assert direct.fingerprint == rematerialized.fingerprint


def test_official_factor_contracts_and_exact_registry_are_machine_readable() -> None:
    assert MOMENTUM.kind is CROSS_SECTION_PERCENTILE.kind is OnlyCalculationKind.FACTOR
    assert MOMENTUM.factor_kind is OnlyFactorKind.TIME_SERIES
    assert CROSS_SECTION_PERCENTILE.factor_kind is OnlyFactorKind.CROSS_SECTION
    assert MOMENTUM.outputs[0].semantic_type == FACTOR_VALUE_SEMANTIC_TYPE
    assert CROSS_SECTION_PERCENTILE.inputs[0].semantic_type == FACTOR_VALUE_SEMANTIC_TYPE
    assert CROSS_SECTION_PERCENTILE.outputs[0].semantic_type == FACTOR_SCORE_SEMANTIC_TYPE
    assert only_calculation_semantic_bounds(FACTOR_SCORE_SEMANTIC_TYPE) == (Decimal(0), Decimal(1))
    assert only_calculation_semantic_bounds(FACTOR_VALUE_SEMANTIC_TYPE) is None
    registry = OnlyCalculationRegistry()
    for registration in reversed(registrations()):
        registry.register(registration)
    assert registry.type_definitions() == (CROSS_SECTION_PERCENTILE, MOMENTUM)
    assert {registration.backend for registration in registrations()} == {
        OnlyCalculationBackendKind.RESEARCH,
        OnlyCalculationBackendKind.TRADING,
    }


def test_all_official_factor_registrations_have_exact_definition_resolvers() -> None:
    official = registrations()
    assert {registration.type_definition for registration in official} == {MOMENTUM, CROSS_SECTION_PERCENTILE}
    for registration in official:
        assert registration.definition_resolver is not None
        assert registration.definition_resolver.type_definition == registration.type_definition


def test_momentum_definition_resolver_preserves_complete_direct_semantics() -> None:
    registry = _factor_registry()
    parameters = {"short_weight": "0.25", "long_weight": Decimal("0.75")}
    short = _reference("a", "return")
    long = _reference("b", "return")
    direct = resolve_momentum(parameters, short, long)
    rematerialized = registry.rematerialize_definition(
        _type_reference(MOMENTUM),
        parameters,
        {"return_short": short, "return_long": long},
    )

    _assert_complete_definition_semantics_equal(direct, rematerialized)
    assert rematerialized.parameters == {
        "long_weight": Decimal("0.75"),
        "short_weight": Decimal("0.25"),
    }


def test_percentile_definition_resolver_reapplies_normalization_and_complete_semantics() -> None:
    registry = _factor_registry()
    value = _reference("c", "factor_value")
    parameters = {"direction": "lower_is_better"}
    direct = resolve_percentile(parameters, value)
    rematerialized = registry.rematerialize_definition(
        _type_reference(CROSS_SECTION_PERCENTILE),
        parameters,
        {"factor_value": value},
    )

    _assert_complete_definition_semantics_equal(direct, rematerialized)
    assert rematerialized.parameters == {"direction": "LOWER_IS_BETTER", "tie_method": "AVERAGE"}


def test_momentum_rematerialization_propagates_binding_and_parameter_identity() -> None:
    registry = _factor_registry()
    reference = _type_reference(MOMENTUM)
    baseline_bindings = {
        "return_short": _reference("a", "return"),
        "return_long": _reference("b", "return"),
    }
    changed_bindings = {
        "return_short": _reference("c", "return"),
        "return_long": _reference("d", "return"),
    }
    baseline = registry.rematerialize_definition(
        reference,
        {"short_weight": "0.5", "long_weight": "0.5"},
        baseline_bindings,
    )
    rebound = registry.rematerialize_definition(
        reference,
        {"short_weight": "0.5", "long_weight": "0.5"},
        changed_bindings,
    )
    reparameterized = registry.rematerialize_definition(
        reference,
        {"short_weight": "0.25", "long_weight": "0.75"},
        baseline_bindings,
    )

    assert baseline.input_bindings == baseline_bindings
    assert rebound.input_bindings == changed_bindings
    assert baseline != rebound
    assert baseline.fingerprint != rebound.fingerprint
    assert baseline != reparameterized
    assert baseline.fingerprint != reparameterized.fingerprint
    assert baseline.type_id == rebound.type_id == reparameterized.type_id
    assert baseline.semantic_version == rebound.semantic_version == reparameterized.semantic_version
    assert baseline.factor_kind is rebound.factor_kind is reparameterized.factor_kind is OnlyFactorKind.TIME_SERIES
    assert baseline.outputs == rebound.outputs == reparameterized.outputs
    assert baseline.numeric == rebound.numeric == reparameterized.numeric


@pytest.mark.parametrize(
    ("type_definition", "parameters", "bindings", "message"),
    (
        (
            MOMENTUM,
            {"hidden_period": 20},
            {"return_short": _reference("a", "return"), "return_long": _reference("b", "return")},
            "unknown calculation parameters",
        ),
        (
            CROSS_SECTION_PERCENTILE,
            {"direction": "SIDEWAYS"},
            {"factor_value": _reference("c", "factor_value")},
            "not an allowed value",
        ),
    ),
)
def test_factor_rematerialization_rejects_invalid_semantic_parameters(
    type_definition, parameters, bindings, message
) -> None:
    with pytest.raises(ValueError, match=message):
        _factor_registry().rematerialize_definition(_type_reference(type_definition), parameters, bindings)


def test_descriptors_are_deterministic_read_only_and_exclude_provider_identity() -> None:
    first = CROSS_SECTION_PERCENTILE.descriptor()
    second = CROSS_SECTION_PERCENTILE.descriptor()
    assert first == second
    assert first["execution_shape"] == "CROSS_SECTION"
    assert first["semantic_bounds"] == {"factor_score": ("0", "1")}
    assert first["parameters"][0]["name"] == "direction"
    assert first["inputs"][0]["semantic_type"] == FACTOR_VALUE_SEMANTIC_TYPE
    assert first["outputs"][0]["semantic_type"] == FACTOR_SCORE_SEMANTIC_TYPE
    assert not {"provider", "class_path", "path", "backend"}.intersection(first)
    with pytest.raises(TypeError):
        first["provider"] = object()
    with pytest.raises(TypeError):
        first["semantic_bounds"]["factor_score"] = ()


def test_momentum_normalizes_decimal_parameters_and_computes_exact_formula_with_null_propagation() -> None:
    definition = _momentum({"short_weight": "0.25", "long_weight": Decimal("2")})
    assert definition.parameters == {"long_weight": Decimal("2"), "short_weight": Decimal("0.25")}
    result = OnlyOfficialResearchFactorBackend().execute(
        definition,
        {
            "return_short": pa.array([Decimal("1"), None, Decimal("-2")], type=_D),
            "return_long": pa.array([Decimal("3"), Decimal("4"), Decimal("0.5")], type=_D),
        },
    )
    assert result["factor_value"].to_pylist() == [Decimal("6.250000000000"), None, Decimal("0.500000000000")]


@pytest.mark.parametrize(
    ("values", "direction", "expected"),
    (
        (
            [Decimal("1"), Decimal("1"), Decimal("2")],
            "HIGHER_IS_BETTER",
            [Decimal("0.250000000000"), Decimal("0.250000000000"), Decimal("1.000000000000")],
        ),
        (
            [Decimal("1"), Decimal("1"), Decimal("2")],
            "LOWER_IS_BETTER",
            [Decimal("0.750000000000"), Decimal("0.750000000000"), Decimal("0E-12")],
        ),
        ([None, Decimal("7"), None], "HIGHER_IS_BETTER", [None, Decimal("0.500000000000"), None]),
        ([None, None], "HIGHER_IS_BETTER", [None, None]),
    ),
)
def test_percentile_freezes_average_ties_direction_missing_and_singleton(values, direction, expected) -> None:
    result = OnlyOfficialResearchFactorBackend().execute(
        _percentile({"direction": direction.lower()}), {"factor_value": pa.array(values, type=_D)}
    )
    assert result["factor_score"].to_pylist() == expected
    assert all(value is None or Decimal(0) <= value <= Decimal(1) for value in expected)


def test_percentile_is_independent_of_physical_instrument_order() -> None:
    backend = OnlyOfficialResearchFactorBackend()
    definition = _percentile()
    semantic = {"A": Decimal("2"), "B": Decimal("1"), "C": Decimal("3"), "D": None}
    observed = []
    for order in (("A", "B", "C", "D"), ("D", "C", "B", "A"), ("C", "A", "D", "B")):
        output = backend.execute(definition, {"factor_value": pa.array([semantic[item] for item in order], type=_D)})[
            "factor_score"
        ].to_pylist()
        observed.append({instrument: value for instrument, value in zip(order, output, strict=True)})
    assert observed[0] == observed[1] == observed[2]


@pytest.mark.parametrize(
    ("definition", "inputs", "message"),
    (
        (_momentum(), {"wrong": pa.array([], type=_D)}, "input names"),
        (
            _momentum(),
            {"return_short": pa.array([1], type=pa.int64()), "return_long": pa.array([1], type=pa.int64())},
            "Arrow Decimal",
        ),
        (
            _momentum(),
            {"return_short": pa.array([Decimal("1")], type=_D), "return_long": pa.array([], type=_D)},
            "lengths differ",
        ),
        (_percentile(), {"wrong": pa.array([], type=_D)}, "input names"),
    ),
)
def test_backends_fail_closed_on_wrong_input_contract(definition, inputs, message) -> None:
    with pytest.raises(ValueError, match=message):
        OnlyOfficialResearchFactorBackend().execute(definition, inputs)


def test_unknown_factor_and_invalid_semantic_parameters_fail_closed() -> None:
    with pytest.raises(ValueError, match="unknown calculation parameters"):
        _momentum({"hidden_period": 20})
    with pytest.raises(ValueError, match="not an allowed value"):
        _percentile({"direction": "SIDEWAYS"})
    with pytest.raises(ValueError, match="unsupported official Factor"):
        OnlyOfficialResearchFactorBackend().execute(replace(_momentum(), semantic_version="2"), {})


def test_backend_defensively_rejects_noncanonical_definition_instances() -> None:
    backend = OnlyOfficialResearchFactorBackend()
    values = {"factor_value": pa.array([Decimal("1")], type=_D)}
    with pytest.raises(ValueError, match="AVERAGE"):
        backend.execute(
            replace(_percentile(), parameters={"direction": "HIGHER_IS_BETTER", "tie_method": "MIN"}), values
        )
    momentum_inputs = {
        "return_short": pa.array([Decimal("1")], type=_D),
        "return_long": pa.array([Decimal("1")], type=_D),
    }
    with pytest.raises(ValueError, match="short_weight"):
        backend.execute(
            replace(_momentum(), parameters={"short_weight": "invalid", "long_weight": Decimal("1")}),
            momentum_inputs,
        )
    with pytest.raises(ValueError, match="output_quantum"):
        backend.execute(
            replace(_momentum(), numeric=replace(_momentum().numeric, output_quantum=None)), momentum_inputs
        )
