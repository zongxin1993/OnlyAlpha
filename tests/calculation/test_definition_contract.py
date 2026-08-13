import subprocess
import sys
from dataclasses import replace
from decimal import Decimal

import pytest

from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyCalculationDataType,
    OnlyCalculationDefinition,
    OnlyCalculationKind,
    OnlyCalculationReference,
    OnlyCalculationTypeDefinition,
    OnlyInputDefinition,
    OnlyMissingValuePolicy,
    OnlyNumericDefinition,
    OnlyOutputDefinition,
    OnlyParameterDefinition,
    OnlyParameterSchema,
    OnlyParameterType,
    OnlyPreReadyOutput,
    OnlyTimestampSemantic,
    OnlyWarmupDefinition,
)
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition, OnlyCalculationNodeDefinition
from onlyalpha.calculation.registry import OnlyCalculationBackendRegistration, OnlyCalculationRegistry


def _type() -> OnlyCalculationTypeDefinition:
    return OnlyCalculationTypeDefinition(
        OnlyCalculationKind.INDICATOR,
        "vendor.indicator.mean",
        "1",
        OnlyParameterSchema((OnlyParameterDefinition("period", OnlyParameterType.INTEGER, False, 20, 1),)),
        (OnlyInputDefinition("value", OnlyCalculationDataType.DECIMAL, True),),
        (OnlyOutputDefinition("value", OnlyCalculationDataType.DECIMAL, True),),
        OnlyMissingValuePolicy.FAIL,
        OnlyTimestampSemantic.EVENT_TIME,
        OnlyNumericDefinition(output_quantum=Decimal("0.001")),
    )


def _definition(parameters: dict[str, object] | None = None, source: str = "bar.close") -> OnlyCalculationDefinition:
    return _type().resolve(
        parameters or {},
        {"value": OnlyCalculationReference(None, "value", source)},
        OnlyWarmupDefinition(20, "samples >= minimum_observations", OnlyPreReadyOutput.PARTIAL, "PARTIAL_WINDOW"),
    )


def test_defaults_order_round_trip_and_presentation_alias_do_not_change_identity() -> None:
    implicit = _definition()
    explicit = _definition({"period": 20})
    reordered = _type().resolve(
        dict(reversed(list({"period": 20}.items()))),
        dict(reversed(list({"value": OnlyCalculationReference(None, "value", "bar.close")}.items()))),
        implicit.warmup,
    )
    assert implicit.fingerprint == explicit.fingerprint == reordered.fingerprint
    assert OnlyCalculationDefinition.from_dict(implicit.to_dict()) == implicit
    assert (
        OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(implicit, "fast"),)).fingerprint
        == OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(implicit, "short"),)).fingerprint
    )
    with pytest.raises(TypeError):
        implicit.parameters["period"] = 21  # type: ignore[index]


def test_semantic_changes_change_fingerprint_and_schema_fails_closed() -> None:
    baseline = _definition()
    assert _definition({"period": 21}).fingerprint != baseline.fingerprint
    assert _definition(source="bar.volume").fingerprint != baseline.fingerprint
    changed_version = replace(_type(), semantic_version="2")
    assert changed_version.resolve({}, baseline.input_bindings, baseline.warmup).fingerprint != baseline.fingerprint
    with pytest.raises(ValueError, match="unknown calculation parameters"):
        _definition({"typo": 1})


def test_fingerprint_is_stable_in_a_fresh_process() -> None:
    script = """
from decimal import Decimal
from onlyalpha.calculation.definition import *
t = OnlyCalculationTypeDefinition(OnlyCalculationKind.INDICATOR, 'vendor.indicator.mean', '1', OnlyParameterSchema((OnlyParameterDefinition('period', OnlyParameterType.INTEGER, False, 20, 1),)), (OnlyInputDefinition('value', OnlyCalculationDataType.DECIMAL, True),), (OnlyOutputDefinition('value', OnlyCalculationDataType.DECIMAL, True),), OnlyMissingValuePolicy.FAIL, OnlyTimestampSemantic.EVENT_TIME, OnlyNumericDefinition(output_quantum=Decimal('0.001')))
d = t.resolve({}, {'value': OnlyCalculationReference(None, 'value', 'bar.close')}, OnlyWarmupDefinition(20, 'samples >= minimum_observations', OnlyPreReadyOutput.PARTIAL, 'PARTIAL_WINDOW'))
print(d.fingerprint)
"""
    result = subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True)
    assert result.stdout.strip() == _definition().fingerprint


def test_graph_validates_dependencies_outputs_types_and_order() -> None:
    source = _definition()
    dependent = _type().resolve(
        {},
        {"value": OnlyCalculationReference(source.fingerprint, "value")},
        source.warmup,
    )
    graph = OnlyCalculationGraphDefinition(
        (OnlyCalculationNodeDefinition(dependent), OnlyCalculationNodeDefinition(source))
    )
    assert tuple(node.fingerprint for node in graph.ordered_nodes) == (source.fingerprint, dependent.fingerprint)
    assert graph.fingerprint == OnlyCalculationGraphDefinition(tuple(reversed(graph.nodes))).fingerprint
    missing = _type().resolve({}, {"value": OnlyCalculationReference("0" * 64, "value")}, source.warmup)
    with pytest.raises(ValueError, match="dependency is missing"):
        OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(missing),))
    invalid_output = _type().resolve({}, {"value": OnlyCalculationReference(source.fingerprint, "nope")}, source.warmup)
    with pytest.raises(ValueError, match="output is missing"):
        OnlyCalculationGraphDefinition(
            (OnlyCalculationNodeDefinition(source), OnlyCalculationNodeDefinition(invalid_output))
        )


class _Factory:
    def create(self, definition: OnlyCalculationDefinition, request: object) -> object:
        return object()


def test_registry_is_exact_and_fail_closed() -> None:
    registry = OnlyCalculationRegistry()
    registration = OnlyCalculationBackendRegistration(_type(), OnlyCalculationBackendKind.TRADING, _Factory())
    registry.register(registration)
    assert (
        registry.resolve(
            OnlyCalculationKind.INDICATOR, "vendor.indicator.mean", "1", OnlyCalculationBackendKind.TRADING
        )
        is registration
    )
    with pytest.raises(ValueError, match="duplicate"):
        registry.register(registration)
    with pytest.raises(ValueError, match="unknown semantic version"):
        registry.resolve(
            OnlyCalculationKind.INDICATOR, "vendor.indicator.mean", "2", OnlyCalculationBackendKind.TRADING
        )
    with pytest.raises(ValueError, match="unsupported backend"):
        registry.resolve(
            OnlyCalculationKind.INDICATOR, "vendor.indicator.mean", "1", OnlyCalculationBackendKind.RESEARCH
        )
    with pytest.raises(ValueError, match="unknown calculation type"):
        registry.resolve(
            OnlyCalculationKind.INDICATOR, "vendor.indicator.unknown", "1", OnlyCalculationBackendKind.TRADING
        )
