import subprocess
import sys
from collections.abc import Mapping
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
    OnlyCalculationTypeReference,
    OnlyFactorKind,
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
from onlyalpha.calculation.registry import (
    OnlyCalculationBackendRegistration,
    OnlyCalculationRegistry,
    OnlyTradingCalculationBackendResolver,
)


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


def test_decimal_and_string_scalars_round_trip_without_type_loss() -> None:
    definition = replace(
        _definition(),
        parameters={"decimal": Decimal("2.00"), "string": "2.00", "integer": 2, "boolean": True, "null": None},
    )
    restored = OnlyCalculationDefinition.from_dict(definition.to_dict())
    assert restored == definition
    assert type(restored.parameters["decimal"]) is Decimal
    assert type(restored.parameters["string"]) is str


def test_semantic_changes_change_fingerprint_and_schema_fails_closed() -> None:
    baseline = _definition()
    assert _definition({"period": 21}).fingerprint != baseline.fingerprint
    assert _definition(source="bar.volume").fingerprint != baseline.fingerprint
    changed_version = replace(_type(), semantic_version="2")
    assert changed_version.resolve({}, baseline.input_bindings, baseline.warmup).fingerprint != baseline.fingerprint
    with pytest.raises(ValueError, match="unknown calculation parameters"):
        _definition({"typo": 1})


@pytest.mark.parametrize(
    ("path", "value", "message"),
    (
        (("schema_version",), 3, "unsupported calculation definition schema"),
        (("unknown",), "future", "fields are invalid"),
        (("inputs", 0, "unknown"), "future", "fields are invalid"),
        (("warmup", "unknown"), "future", "fields are invalid"),
        (("numeric", "precision"), "28", "must be an integer"),
        (("outputs", 0, "nullable"), 1, "must be a boolean"),
        (("inputs", 0, "dimensions"), "TIME", "array of strings"),
    ),
)
def test_definition_deserialization_fails_closed(path, value, message) -> None:
    payload = _mutable(_definition().to_dict())
    target = payload
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(ValueError, match=message):
        OnlyCalculationDefinition.from_dict(payload)


def test_definition_deserialization_rejects_missing_and_invalid_reference() -> None:
    payload = _mutable(_definition().to_dict())
    del payload["timestamp"]
    with pytest.raises(ValueError, match="fields are invalid"):
        OnlyCalculationDefinition.from_dict(payload)
    payload = _mutable(_definition().to_dict())
    payload["input_bindings"]["value"]["node_fingerprint"] = "not-a-digest"
    payload["input_bindings"]["value"]["source"] = None
    with pytest.raises(ValueError, match="SHA-256"):
        OnlyCalculationDefinition.from_dict(payload)
    payload = _mutable(_definition().to_dict())
    payload["schema_version"] = 1
    with pytest.raises(ValueError, match="unsupported calculation definition schema"):
        OnlyCalculationDefinition.from_dict(payload)


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
    assert OnlyCalculationGraphDefinition.from_dict(graph.to_dict()).fingerprint == graph.fingerprint
    graph_payload = _mutable(graph.to_dict())
    graph_payload["schema_version"] = 2
    with pytest.raises(ValueError, match="unsupported calculation graph schema"):
        OnlyCalculationGraphDefinition.from_dict(graph_payload)


@pytest.mark.parametrize(
    ("field", "target", "source", "reason"),
    (
        ("data_type", OnlyCalculationDataType.INTEGER, OnlyCalculationDataType.DECIMAL, "data_type"),
        ("nullable", False, True, "nullability"),
        ("dimensions", ("INSTRUMENT",), ("TIME",), "dimensions"),
        ("semantic_type", "RETURN", "PRICE", "semantic_type"),
        ("unit", "CNY", "USD", "unit"),
    ),
)
def test_graph_rejects_every_semantic_port_mismatch(field, target, source, reason) -> None:
    upstream_type = replace(_type(), outputs=(replace(_type().outputs[0], **{field: source}),))
    upstream = upstream_type.resolve(
        {}, {"value": OnlyCalculationReference(None, "value", "bar.close")}, _definition().warmup
    )
    downstream_type = replace(_type(), inputs=(replace(_type().inputs[0], **{field: target}),))
    downstream = downstream_type.resolve(
        {}, {"value": OnlyCalculationReference(upstream.fingerprint, "value")}, _definition().warmup
    )
    with pytest.raises(ValueError, match=reason):
        OnlyCalculationGraphDefinition(
            (OnlyCalculationNodeDefinition(upstream), OnlyCalculationNodeDefinition(downstream))
        )


def test_graph_accepts_non_nullable_output_for_nullable_input_and_diamond_order_is_stable() -> None:
    root_type = replace(_type(), outputs=(replace(_type().outputs[0], nullable=False),))
    root = root_type.resolve({}, {"value": OnlyCalculationReference(None, "value", "bar.close")}, _definition().warmup)
    left = replace(_type(), type_id="vendor.indicator.left").resolve(
        {}, {"value": OnlyCalculationReference(root.fingerprint, "value")}, _definition().warmup
    )
    right = replace(_type(), type_id="vendor.indicator.right").resolve(
        {}, {"value": OnlyCalculationReference(root.fingerprint, "value")}, _definition().warmup
    )
    sink_type = replace(
        _type(),
        type_id="vendor.indicator.sink",
        inputs=(
            replace(_type().inputs[0], name="left"),
            replace(_type().inputs[0], name="right"),
        ),
    )
    sink = sink_type.resolve(
        {},
        {
            "left": OnlyCalculationReference(left.fingerprint, "value"),
            "right": OnlyCalculationReference(right.fingerprint, "value"),
        },
        _definition().warmup,
    )
    nodes = tuple(OnlyCalculationNodeDefinition(item) for item in (sink, right, root, left))
    graph = OnlyCalculationGraphDefinition(nodes)
    assert graph.fingerprint == OnlyCalculationGraphDefinition(tuple(reversed(nodes))).fingerprint
    assert graph.ordered_nodes[-1].fingerprint == sink.fingerprint


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
    research_provider = object()
    research = OnlyCalculationBackendRegistration(_type(), OnlyCalculationBackendKind.RESEARCH, research_provider)
    registry.register(research)
    assert (
        registry.resolve(
            OnlyCalculationKind.INDICATOR, "vendor.indicator.mean", "1", OnlyCalculationBackendKind.RESEARCH
        ).provider
        is research_provider
    )
    malformed = OnlyCalculationRegistry()
    malformed.register(OnlyCalculationBackendRegistration(_type(), OnlyCalculationBackendKind.TRADING, object()))
    with pytest.raises(TypeError, match="TRADING.*create"):
        OnlyTradingCalculationBackendResolver(malformed).create(_definition(), object())


def test_type_reference_is_exact_strict_and_backend_neutral() -> None:
    reference = OnlyCalculationTypeReference(OnlyCalculationKind.FACTOR, "vendor.factor.value", "1")
    assert OnlyCalculationTypeReference.from_dict(reference.to_dict()) == reference
    with pytest.raises(ValueError, match="fields are invalid"):
        OnlyCalculationTypeReference.from_dict({**reference.to_dict(), "backend": "TRADING"})


def test_formal_factor_semantics_are_runtime_independent_and_class_path_is_not_identity() -> None:
    factor = OnlyCalculationDefinition(
        kind=OnlyCalculationKind.FACTOR,
        type_id="vendor.factor.momentum",
        semantic_version="1",
        parameters={"lookback": 20},
        inputs=(
            OnlyInputDefinition(
                "returns", OnlyCalculationDataType.DECIMAL, False, ("TIME", "INSTRUMENT"), "RETURN", "RATIO"
            ),
        ),
        input_bindings={"returns": OnlyCalculationReference(None, "value", "dataset.returns")},
        outputs=(OnlyOutputDefinition("score", OnlyCalculationDataType.DECIMAL, False, ("TIME",), "RANK", None),),
        warmup=OnlyWarmupDefinition(20, "complete lookback", OnlyPreReadyOutput.NULL, "NO_PARTIAL_WINDOW"),
        missing_values=OnlyMissingValuePolicy.FAIL,
        timestamp=OnlyTimestampSemantic.AVAILABILITY_TIME,
        numeric=OnlyNumericDefinition(),
        factor_kind=OnlyFactorKind.CROSS_SECTION,
    )
    payload = factor.to_dict()
    assert OnlyCalculationDefinition.from_dict(payload) == factor
    assert "class_path" not in payload
    assert "runtime_id" not in payload
    assert "cluster_id" not in payload


def test_factor_factory_requires_implementation_to_match_exact_semantic_reference() -> None:
    from onlyalpha.factor.factory import OnlyFactorCreateRequest, OnlyFactorFactory

    reference = OnlyCalculationTypeReference(OnlyCalculationKind.FACTOR, "onlyalpha.test.factor.macd", "1")
    request = OnlyFactorCreateRequest(
        reference,
        "onlyalpha_test_plugin.macd_plugin:OnlyTestMacdFactor",
        "onlyalpha_test_plugin.macd_plugin:OnlyTestMacdFactorConfig",
        {"factor_id": "factor", "factor_type": "TIME_SERIES", "indicator_specs": ()},
    )
    with pytest.raises(ValueError, match="requires one indicator"):
        OnlyFactorFactory().create(request)
    with pytest.raises(ValueError, match="exact calculation reference"):
        OnlyFactorFactory().create(replace(request, calculation_reference=replace(reference, semantic_version="2")))


def _mutable(value):
    if isinstance(value, Mapping):
        return {key: _mutable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_mutable(item) for item in value]
    return value
