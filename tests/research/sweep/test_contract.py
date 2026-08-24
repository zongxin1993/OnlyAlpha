from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from onlyalpha.calculation import OnlyCalculationKind
from onlyalpha.research import (
    OnlyResearchGraphTemplate,
    OnlyResearchGraphTemplateNode,
    OnlyResearchSweepDefinition,
    OnlyResearchSweepError,
    OnlyResearchSweepParameterDimension,
    OnlyResearchSweepParameterTarget,
    OnlyResearchTemplateInputBinding,
    OnlyResearchTemplateReference,
)
from tests.research.sweep.support import definition, factor_template, reference, registry


def test_definition_and_template_round_trip_are_exact_immutable_and_type_preserving() -> None:
    original = definition(candidates=(20, Decimal("0.50")))
    restored = OnlyResearchSweepDefinition.from_dict(original.to_dict())
    assert restored == original
    assert {type(value) for value in restored.dimensions[0].candidates} == {int, Decimal}
    with pytest.raises(FrozenInstanceError):
        restored.schema_version = 2
    assert not hasattr(restored, "fingerprint")


@pytest.mark.parametrize("field", ("schema_version", "dataset_snapshot_fingerprint", "graph_template", "dimensions"))
def test_definition_missing_or_unknown_fields_fail_closed(field) -> None:
    payload = dict(definition().to_dict())
    del payload[field]
    with pytest.raises(OnlyResearchSweepError):
        OnlyResearchSweepDefinition.from_dict(payload)
    payload = dict(definition().to_dict())
    payload["future"] = True
    with pytest.raises(OnlyResearchSweepError):
        OnlyResearchSweepDefinition.from_dict(payload)


def test_template_rejects_empty_duplicate_missing_self_and_cycle() -> None:
    node = factor_template().nodes[0]
    with pytest.raises(OnlyResearchSweepError, match="cannot be empty"):
        OnlyResearchGraphTemplate(())
    with pytest.raises(OnlyResearchSweepError) as duplicate:
        OnlyResearchGraphTemplate((node, node))
    assert duplicate.value.code == "SWEEP_TEMPLATE_NODE_DUPLICATE"
    missing = OnlyResearchGraphTemplateNode(
        "consumer",
        reference(OnlyCalculationKind.FACTOR, "onlyalpha.factor.cross_section_percentile"),
        {},
        (OnlyResearchTemplateInputBinding("factor_value", OnlyResearchTemplateReference("missing", "value")),),
    )
    with pytest.raises(OnlyResearchSweepError, match="unknown dependency"):
        OnlyResearchGraphTemplate((node, missing))
    self_ref = OnlyResearchGraphTemplateNode(
        "self",
        node.type_reference,
        {},
        (OnlyResearchTemplateInputBinding("value", OnlyResearchTemplateReference("self", "value")),),
    )
    with pytest.raises(OnlyResearchSweepError, match="self dependency"):
        OnlyResearchGraphTemplate((self_ref,))
    left = OnlyResearchGraphTemplateNode(
        "left",
        node.type_reference,
        {},
        (OnlyResearchTemplateInputBinding("value", OnlyResearchTemplateReference("right", "value")),),
    )
    right = OnlyResearchGraphTemplateNode(
        "right",
        node.type_reference,
        {},
        (OnlyResearchTemplateInputBinding("value", OnlyResearchTemplateReference("left", "value")),),
    )
    with pytest.raises(OnlyResearchSweepError, match="cycle"):
        OnlyResearchGraphTemplate((left, right))


def test_duplicate_input_target_dimension_target_and_empty_candidates_fail_closed() -> None:
    node = factor_template().nodes[0]
    binding = OnlyResearchTemplateInputBinding("value", OnlyResearchTemplateReference(None, "value", "bar.close"))
    with pytest.raises(OnlyResearchSweepError, match="duplicate input"):
        OnlyResearchGraphTemplateNode("x", node.type_reference, {}, (binding, binding))
    target = OnlyResearchSweepParameterTarget("short", "period")
    with pytest.raises(OnlyResearchSweepError, match="cannot be empty"):
        OnlyResearchSweepParameterDimension(target, ())
    dimension = OnlyResearchSweepParameterDimension(target, (1,))
    with pytest.raises(OnlyResearchSweepError) as duplicate:
        OnlyResearchSweepDefinition("a" * 64, factor_template(), (dimension, dimension))
    assert duplicate.value.code == "SWEEP_DUPLICATE_PARAMETER_TARGET"


@pytest.mark.parametrize("fingerprint", ("short", "A" * 64))
def test_dataset_fingerprint_validation_is_exact(fingerprint) -> None:
    with pytest.raises(OnlyResearchSweepError) as raised:
        definition(fingerprint)
    assert raised.value.code == "SWEEP_DEFINITION_INVALID"


def test_unknown_type_target_parameter_invalid_value_and_duplicate_normalization_fail_closed() -> None:
    unknown = OnlyResearchGraphTemplate(
        (OnlyResearchGraphTemplateNode("x", reference(OnlyCalculationKind.INDICATOR, "vendor.unknown")),)
    )
    unknown_definition = OnlyResearchSweepDefinition(
        "a" * 64,
        unknown,
        (OnlyResearchSweepParameterDimension(OnlyResearchSweepParameterTarget("x", "period"), (1,)),),
    )
    with pytest.raises(OnlyResearchSweepError, match="unknown calculation type"):
        registry_plan(unknown_definition)
    missing_target = OnlyResearchSweepDefinition(
        "a" * 64,
        factor_template(),
        (OnlyResearchSweepParameterDimension(OnlyResearchSweepParameterTarget("missing", "period"), (1,)),),
    )
    with pytest.raises(OnlyResearchSweepError) as raised:
        registry_plan(missing_target)
    assert raised.value.code == "SWEEP_TARGET_NOT_FOUND"
    unknown_parameter = OnlyResearchSweepDefinition(
        "a" * 64,
        factor_template(),
        (OnlyResearchSweepParameterDimension(OnlyResearchSweepParameterTarget("short", "missing"), (1,)),),
    )
    with pytest.raises(OnlyResearchSweepError) as raised:
        registry_plan(unknown_parameter)
    assert raised.value.code == "SWEEP_PARAMETER_UNKNOWN"
    with pytest.raises(OnlyResearchSweepError) as raised:
        registry_plan(definition(candidates=(0,)))
    assert raised.value.code == "SWEEP_PARAMETER_INVALID"
    with pytest.raises(OnlyResearchSweepError) as raised:
        registry_plan(definition(candidates=(20, "20")))
    assert raised.value.code == "SWEEP_DUPLICATE_PARAMETER_VALUE"


def registry_plan(value):
    from onlyalpha.research import OnlyResearchSweepPlanner

    return OnlyResearchSweepPlanner(registry()).plan(value)


def test_contract_readers_and_value_objects_reject_malformed_shapes() -> None:
    from onlyalpha.research import (
        OnlyResearchJobDisposition,
        OnlyResearchSweepCellOutcome,
        OnlyResearchSweepOutcome,
        OnlyResearchSweepPlanner,
    )

    with pytest.raises(OnlyResearchSweepError):
        OnlyResearchTemplateReference(None, "value", None)
    with pytest.raises(OnlyResearchSweepError):
        OnlyResearchTemplateReference(1, "value")  # type: ignore[arg-type]
    with pytest.raises(OnlyResearchSweepError):
        OnlyResearchTemplateReference.from_dict({"template_node_id": None, "output_name": 1, "source": "bar.close"})
    with pytest.raises(OnlyResearchSweepError):
        OnlyResearchTemplateInputBinding("value", object())  # type: ignore[arg-type]
    with pytest.raises(OnlyResearchSweepError):
        OnlyResearchTemplateInputBinding.from_dict({"input_name": "value", "reference": "bad"})
    with pytest.raises(OnlyResearchSweepError):
        OnlyResearchGraphTemplateNode("bad id", factor_template().nodes[0].type_reference)
    with pytest.raises(OnlyResearchSweepError):
        OnlyResearchGraphTemplateNode("x", object())  # type: ignore[arg-type]
    with pytest.raises(OnlyResearchSweepError):
        OnlyResearchGraphTemplateNode.from_dict(
            {"template_node_id": "x", "type_reference": {}, "parameters": [], "input_bindings": [], "alias": None}
        )
    with pytest.raises(OnlyResearchSweepError):
        OnlyResearchGraphTemplate.from_dict({"schema_version": True, "nodes": []})
    with pytest.raises(OnlyResearchSweepError):
        OnlyResearchSweepParameterTarget.from_dict({"template_node_id": 1, "parameter_name": "period"})
    with pytest.raises(OnlyResearchSweepError):
        OnlyResearchSweepParameterDimension.from_dict({"target": {}, "candidates": "bad"})
    with pytest.raises(OnlyResearchSweepError):
        OnlyResearchSweepDefinition.from_dict(
            {"schema_version": True, "dataset_snapshot_fingerprint": "a" * 64, "graph_template": {}, "dimensions": []}
        )
    with pytest.raises(TypeError):
        OnlyResearchSweepPlanner(object())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        OnlyResearchSweepPlanner(registry(), max_cells=0)
    with pytest.raises(OnlyResearchSweepError):
        OnlyResearchSweepPlanner(registry()).plan(object())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        OnlyResearchSweepOutcome(1, 0, 0, ())
    cell = OnlyResearchSweepCellOutcome(
        1,
        (),
        "a" * 64,
        "b" * 64,
        "c" * 64,
        OnlyResearchJobDisposition.REUSED,
    )
    with pytest.raises(ValueError, match="counts"):
        OnlyResearchSweepOutcome(1, 1, 1, (cell,))
    with pytest.raises(ValueError, match="ordinals"):
        OnlyResearchSweepOutcome(1, 0, 1, (cell,))
    with pytest.raises(ValueError, match="ordinal"):
        OnlyResearchSweepCellOutcome(-1, (), "a" * 64, "b" * 64, "c" * 64, OnlyResearchJobDisposition.REUSED)
