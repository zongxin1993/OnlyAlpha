import os
import subprocess
import sys
from decimal import ROUND_DOWN, Decimal, localcontext

import pyarrow as pa
import pytest
from onlyalpha_plugin_operators.provider import quant_asset_provider
from onlyalpha_plugin_operators.registration import (
    ABS,
    ADD,
    CROSS_SECTION_DEMEAN,
    CROSS_SECTION_RANK,
    CROSS_SECTION_ZSCORE,
    DECAY_LINEAR,
    DELAY,
    DELTA,
    DIVIDE,
    LOG,
    MULTIPLY,
    P0_TYPES,
    ROLLING_CORRELATION,
    ROLLING_COVARIANCE,
    ROLLING_MAX,
    ROLLING_MEAN,
    ROLLING_MIN,
    ROLLING_STD,
    ROLLING_SUM,
    ROLLING_VAR,
    SCALE,
    SIGN,
    SUBTRACT,
    TS_RANK,
    registrations,
    resolve_operator,
)

from onlyalpha.calculation import (
    OnlyCalculationBackendKind,
    OnlyCalculationGraphDefinition,
    OnlyCalculationNodeDefinition,
    OnlyCalculationReference,
    OnlyCalculationStateCapability,
)

_D = pa.decimal128(38, 12)
_SOURCE = OnlyCalculationReference(None, "value", "dataset.value")


def _definition(type_definition, parameters=None):
    bindings = {
        item.name: OnlyCalculationReference(None, item.name, f"dataset.{item.name}") for item in type_definition.inputs
    }
    return resolve_operator(type_definition, parameters or {}, **bindings)


def _registration(type_definition, backend):
    return next(item for item in registrations() if item.type_definition is type_definition and item.backend is backend)


@pytest.mark.parametrize(
    "type_definition",
    (
        ADD,
        SUBTRACT,
        MULTIPLY,
        DIVIDE,
        ABS,
        SIGN,
        LOG,
        DELAY,
        DELTA,
        ROLLING_MEAN,
        ROLLING_SUM,
        ROLLING_STD,
        ROLLING_VAR,
        ROLLING_MIN,
        ROLLING_MAX,
        ROLLING_COVARIANCE,
        ROLLING_CORRELATION,
        TS_RANK,
        SCALE,
        DECAY_LINEAR,
    ),
)
def test_all_time_series_p0_research_trading_and_restore_are_exact(type_definition) -> None:
    parameters = {"period": 3} if any(item.name == "period" for item in type_definition.parameters.fields) else {}
    if type_definition is SCALE:
        parameters = {"factor": Decimal("2.5")}
    definition = _definition(type_definition, parameters)
    left = [Decimal("1"), Decimal("2"), None, Decimal("4"), Decimal("5"), Decimal("8")]
    right = [Decimal("2"), Decimal("0"), Decimal("3"), Decimal("4"), Decimal("5"), Decimal("10")]
    columns = {item.name: (left if item.name in {"value", "left"} else right) for item in definition.inputs}
    research = _registration(type_definition, OnlyCalculationBackendKind.RESEARCH).provider.execute(
        definition, {name: pa.array(values, type=_D) for name, values in columns.items()}
    )
    expected = {name: array.to_pylist() for name, array in research.items()}
    trading_registration = _registration(type_definition, OnlyCalculationBackendKind.TRADING)
    uninterrupted = trading_registration.provider.create(definition, object())
    actual = {name: [] for name in expected}
    for row in zip(*(columns[name] for name in columns), strict=True):
        result = uninterrupted.update(dict(zip(columns, row, strict=True)))
        for name in actual:
            actual[name].append(result[name])
    assert actual == expected
    if trading_registration.state_capability is OnlyCalculationStateCapability.CHECKPOINTABLE:
        split = 4
        original = trading_registration.provider.create(definition, object())
        rows = [dict(zip(columns, row, strict=True)) for row in zip(*(columns[name] for name in columns), strict=True)]
        for row in rows[:split]:
            original.update(row)
        restored = trading_registration.provider.create(definition, object())
        restored.restore_checkpoint(original.capture_checkpoint())
        assert [original.update(row) for row in rows[split:]] == [restored.update(row) for row in rows[split:]]


def test_invalid_domains_population_statistics_and_rank_ties_are_exact() -> None:
    divide = _definition(DIVIDE)
    result = (
        _registration(DIVIDE, OnlyCalculationBackendKind.RESEARCH)
        .provider.execute(
            divide, {"left": pa.array([Decimal("1")], type=_D), "right": pa.array([Decimal("0")], type=_D)}
        )["value"]
        .to_pylist()
    )
    assert result == [None]
    log = _definition(LOG)
    assert _registration(LOG, OnlyCalculationBackendKind.RESEARCH).provider.execute(
        log, {"value": pa.array([Decimal("0"), Decimal("-1")], type=_D)}
    )["value"].to_pylist() == [None, None]
    correlation = _definition(ROLLING_CORRELATION, {"period": 3})
    constant = pa.array([Decimal("5")] * 3, type=_D)
    monotonic = pa.array([Decimal("1"), Decimal("2"), Decimal("3")], type=_D)
    assert _registration(ROLLING_CORRELATION, OnlyCalculationBackendKind.RESEARCH).provider.execute(
        correlation, {"left": constant, "right": monotonic}
    )["value"].to_pylist() == [None, None, None]
    rank = _definition(TS_RANK, {"period": 5})
    assert _registration(TS_RANK, OnlyCalculationBackendKind.RESEARCH).provider.execute(
        rank, {"value": pa.array([Decimal("1"), Decimal("1"), Decimal("2"), Decimal("2"), Decimal("3")], type=_D)}
    )["value"].to_pylist()[-1] == Decimal("1.000000000000")


def test_operator_results_ignore_caller_decimal_context() -> None:
    definition = _definition(ROLLING_MEAN, {"period": 2})
    backend = _registration(ROLLING_MEAN, OnlyCalculationBackendKind.RESEARCH).provider
    inputs = {"value": pa.array([Decimal("1.234567890123"), Decimal("9.876543210987")], type=_D)}
    expected = backend.execute(definition, inputs)["value"].to_pylist()
    with localcontext() as caller:
        caller.prec = 4
        caller.rounding = ROUND_DOWN
        assert backend.execute(definition, inputs)["value"].to_pylist() == expected


def test_shared_numeric_vectors_cover_alternating_quantum_large_and_population_results() -> None:
    backend = _registration(SIGN, OnlyCalculationBackendKind.RESEARCH).provider
    sign = _definition(SIGN)
    assert (
        backend.execute(sign, {"value": pa.array([Decimal("1"), Decimal("-1"), Decimal("1"), Decimal("-1")], type=_D)})[
            "value"
        ].to_pylist()
        == [Decimal("1.000000000000"), Decimal("-1.000000000000")] * 2
    )

    rolling_sum = _definition(ROLLING_SUM, {"period": 3})
    assert _registration(ROLLING_SUM, OnlyCalculationBackendKind.RESEARCH).provider.execute(
        rolling_sum,
        {"value": pa.array([Decimal("0.000000000001"), Decimal("0.000000000002"), Decimal("0.000000000003")], type=_D)},
    )["value"].to_pylist()[-1] == Decimal("0.000000000006")

    add = _definition(ADD)
    assert _registration(ADD, OnlyCalculationBackendKind.RESEARCH).provider.execute(
        add,
        {"left": pa.array([Decimal("999999999999999")], type=_D), "right": pa.array([Decimal("1")], type=_D)},
    )["value"].to_pylist() == [Decimal("1000000000000000.000000000000")]

    variance = _definition(ROLLING_VAR, {"period": 3})
    assert _registration(ROLLING_VAR, OnlyCalculationBackendKind.RESEARCH).provider.execute(
        variance, {"value": pa.array([Decimal("1"), Decimal("2"), Decimal("3")], type=_D)}
    )["value"].to_pylist()[-1] == Decimal("0.666666666667")

    cross_zscore = _definition(CROSS_SECTION_ZSCORE)
    assert _registration(CROSS_SECTION_ZSCORE, OnlyCalculationBackendKind.RESEARCH).provider.execute(
        cross_zscore, {"value": pa.array([Decimal("5"), Decimal("5"), None], type=_D)}
    )["zscore"].to_pylist() == [None, None, None]


@pytest.mark.parametrize("type_definition", (CROSS_SECTION_RANK, CROSS_SECTION_ZSCORE, CROSS_SECTION_DEMEAN))
def test_cross_section_p0_is_research_only_and_preserves_missing(type_definition) -> None:
    definition = _definition(type_definition)
    values = pa.array([Decimal("1"), None, Decimal("1"), Decimal("3")], type=_D)
    output = (
        _registration(type_definition, OnlyCalculationBackendKind.RESEARCH)
        .provider.execute(definition, {"value": values})[type_definition.outputs[0].name]
        .to_pylist()
    )
    assert output[1] is None
    assert not any(
        item.type_definition is type_definition and item.backend is OnlyCalculationBackendKind.TRADING
        for item in registrations()
    )


def test_p0_discovery_and_provider_version_are_complete() -> None:
    provider = quant_asset_provider()
    assert provider.manifest.provider_id == "onlyalpha.operator.library"
    assert provider.manifest.provider_version == "3"
    assert {item.type_definition for item in provider.calculation_registrations} == set(P0_TYPES)
    assert provider.content_fingerprint == "9b50f3c60dfb9e20621bb375a8ea60ac8636c3e7ab33124a87764a9b2f8f1213"
    assert provider.content_fingerprint == quant_asset_provider().content_fingerprint


def test_operator_composition_identity_is_order_independent_and_parameter_sensitive() -> None:
    first = resolve_operator(ROLLING_MEAN, {"period": 2}, value=_SOURCE)
    second = resolve_operator(ABS, {}, value=OnlyCalculationReference(first.fingerprint, "value"))
    nodes = (OnlyCalculationNodeDefinition(first), OnlyCalculationNodeDefinition(second))
    graph = OnlyCalculationGraphDefinition(nodes)
    assert graph.fingerprint == OnlyCalculationGraphDefinition(tuple(reversed(nodes))).fingerprint
    changed = resolve_operator(ROLLING_MEAN, {"period": 3}, value=_SOURCE)
    assert changed.fingerprint != first.fingerprint


def test_representative_composition_is_fresh_process_hash_seed_independent() -> None:
    program = """
from onlyalpha.calculation import OnlyCalculationGraphDefinition, OnlyCalculationNodeDefinition, OnlyCalculationReference
from onlyalpha_plugin_operators.registration import DELTA, ROLLING_MEAN, resolve_operator
source = OnlyCalculationReference(None, 'value', 'dataset.value')
mean = resolve_operator(ROLLING_MEAN, {'period': 5}, value=source)
delta = resolve_operator(DELTA, {'period': 2}, value=OnlyCalculationReference(mean.fingerprint, 'value'))
print(OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(delta), OnlyCalculationNodeDefinition(mean))).fingerprint)
"""
    fingerprints = []
    for seed in ("1", "987654"):
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            [sys.executable, "-c", program],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        fingerprints.append(completed.stdout.strip())
    assert len(set(fingerprints)) == 1
