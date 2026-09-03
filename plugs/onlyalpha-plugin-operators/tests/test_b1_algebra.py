import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from decimal import (
    ROUND_DOWN,
    Clamped,
    Decimal,
    Inexact,
    Rounded,
    Subnormal,
    Underflow,
    localcontext,
)
from threading import Barrier

import pyarrow as pa
import pytest
from onlyalpha_plugin_operators.provider import quant_asset_provider
from onlyalpha_plugin_operators.registration import (
    ABS,
    ADD,
    CROSS_SECTION_DEMEAN,
    CROSS_SECTION_PERCENTILE,
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


def _make_hostile(caller, variant=0):
    caller.prec = 4 if variant == 0 else 6
    caller.rounding = ROUND_DOWN
    caller.Emin = -5 if variant == 0 else -3
    caller.Emax = 5 if variant == 0 else 3
    caller.clamp = 1
    for signal in (Inexact, Rounded, Underflow, Subnormal):
        caller.traps[signal] = True
        caller.flags[signal] = True
    caller.flags[Clamped] = True


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


@pytest.mark.parametrize(
    ("type_definition", "parameters", "inputs"),
    (
        (MULTIPLY, {}, {"left": ("1E4",), "right": ("1E4",)}),
        (DIVIDE, {}, {"left": ("1",), "right": ("3",)}),
        (LOG, {}, {"value": ("2",)}),
        (ROLLING_STD, {"period": 3}, {"value": ("1", "2", "4")}),
        (
            ROLLING_CORRELATION,
            {"period": 3},
            {"left": ("1", "2", "4"), "right": ("2", "5", "9")},
        ),
        (DECAY_LINEAR, {"period": 3}, {"value": ("1", "2", "4")}),
        (CROSS_SECTION_ZSCORE, {}, {"value": ("1", "2", "4")}),
        (TS_RANK, {"period": 3}, {"value": ("1", "2", "4")}),
    ),
)
def test_representative_operators_ignore_complete_hostile_caller_context(type_definition, parameters, inputs) -> None:
    definition = _definition(type_definition, parameters)
    backend = _registration(type_definition, OnlyCalculationBackendKind.RESEARCH).provider
    arrays = {name: pa.array([Decimal(value) for value in values], type=_D) for name, values in inputs.items()}
    expected = {name: values.to_pylist() for name, values in backend.execute(definition, arrays).items()}
    with localcontext() as caller:
        _make_hostile(caller)
        assert {name: values.to_pylist() for name, values in backend.execute(definition, arrays).items()} == expected


def test_stateful_operator_checkpoint_continues_across_hostile_contexts() -> None:
    definition = _definition(ROLLING_STD, {"period": 3})
    registration = _registration(ROLLING_STD, OnlyCalculationBackendKind.TRADING)
    values = tuple(Decimal(value) for value in ("1", "2", "4", "8", "16"))
    research = (
        _registration(ROLLING_STD, OnlyCalculationBackendKind.RESEARCH)
        .provider.execute(definition, {"value": pa.array(values, type=_D)})["value"]
        .to_pylist()
    )
    with localcontext() as caller_a:
        _make_hostile(caller_a, 0)
        uninterrupted = registration.provider.create(definition, object())
        streamed = [uninterrupted.update({"value": value})["value"] for value in values]
        original = registration.provider.create(definition, object())
        for value in values[:3]:
            original.update({"value": value})
        checkpoint = original.capture_checkpoint()
    with localcontext() as caller_b:
        _make_hostile(caller_b, 1)
        restored = registration.provider.create(definition, object())
        restored.restore_checkpoint(checkpoint)
        continued = [restored.update({"value": value})["value"] for value in values[3:]]
    assert streamed == research
    assert continued == research[3:]


def test_operator_execution_is_thread_context_independent() -> None:
    definition = _definition(DIVIDE)
    backend = _registration(DIVIDE, OnlyCalculationBackendKind.RESEARCH).provider
    inputs = {
        "left": pa.array([Decimal("1"), Decimal("1E4")], type=_D),
        "right": pa.array([Decimal("3"), Decimal("0.0001")], type=_D),
    }
    barrier = Barrier(2)

    def execute(variant):
        with localcontext() as caller:
            _make_hostile(caller, variant)
            barrier.wait()
            return backend.execute(definition, inputs)["value"].to_pylist()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = tuple(executor.submit(execute, variant) for variant in (0, 1))
    assert futures[0].result() == futures[1].result()


def test_operator_execution_is_process_default_context_independent() -> None:
    program = """
from decimal import Inexact, Rounded, Subnormal, Underflow, Decimal, getcontext
import pyarrow as pa
from onlyalpha.calculation import OnlyCalculationBackendKind, OnlyCalculationReference
from onlyalpha_plugin_operators.registration import MULTIPLY, registrations, resolve_operator
variant = int(__import__('os').environ['ONLYALPHA_CONTEXT_VARIANT'])
caller = getcontext()
caller.prec = 4 + variant
caller.Emin = -5 + variant
caller.Emax = 5 - variant
caller.clamp = 1
for signal in (Inexact, Rounded, Subnormal, Underflow):
    caller.traps[signal] = True
    caller.flags[signal] = True
definition = resolve_operator(
    MULTIPLY, {},
    left=OnlyCalculationReference(None, 'left', 'dataset.left'),
    right=OnlyCalculationReference(None, 'right', 'dataset.right'),
)
registration = next(item for item in registrations() if item.type_definition is MULTIPLY and item.backend is OnlyCalculationBackendKind.RESEARCH)
value = registration.provider.execute(
    definition,
    {'left': pa.array([Decimal('1E4')], type=pa.decimal128(38, 12)), 'right': pa.array([Decimal('1E4')], type=pa.decimal128(38, 12))},
)['value'].to_pylist()
print(value)
"""
    outputs = []
    for variant in ("0", "1"):
        environment = dict(os.environ)
        environment["ONLYALPHA_CONTEXT_VARIANT"] = variant
        outputs.append(
            subprocess.run(
                [sys.executable, "-c", program],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            ).stdout.strip()
        )
    assert outputs == ["[Decimal('100000000.000000000000')]"] * 2


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
    assert provider.manifest.provider_version == "4"
    assert {item.type_definition for item in provider.calculation_registrations} == set(P0_TYPES)
    assert provider.content_fingerprint == "aa0131efd0f7c9c033ca4423fa4b20ad70940cba3f41f4782b870f62ccdba122"
    assert all(
        any(
            dependency.dependency_id == "onlyalpha.decimal.execution"
            for dependency in item.implementation_manifest.semantic_dependencies
        )
        for item in provider.calculation_registrations
    )
    assert provider.content_fingerprint == quant_asset_provider().content_fingerprint


def test_operator_composition_identity_is_order_independent_and_parameter_sensitive() -> None:
    first = resolve_operator(ROLLING_MEAN, {"period": 2}, value=_SOURCE)
    second = resolve_operator(ABS, {}, value=OnlyCalculationReference(first.fingerprint, "value"))
    nodes = (OnlyCalculationNodeDefinition(first), OnlyCalculationNodeDefinition(second))
    graph = OnlyCalculationGraphDefinition(nodes)
    assert first.fingerprint == "40c666c455783fee14e8af4e70062f470a7b060e495a992c8c9800de356e28ef"
    assert _definition(CROSS_SECTION_PERCENTILE).fingerprint == (
        "9259f6b3d79ef6c801996c5ffc5bcef7fdb07f52a37948d00fa1385948c3fa0d"
    )
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
