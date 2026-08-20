from __future__ import annotations

import json
import os
import subprocess
import sys
from decimal import Decimal

import pytest

from onlyalpha.calculation import OnlyCalculationKind
from onlyalpha.research import (
    OnlyResearchCalculationSpec,
    OnlyResearchGraphTemplate,
    OnlyResearchGraphTemplateNode,
    OnlyResearchSpecification,
    OnlyResearchSpecificationError,
    OnlyResearchSweepParameterDimension,
    OnlyResearchSweepParameterTarget,
)
from tests.research.specification.support import registry, specification
from tests.research.sweep.support import factor_template, reference


def test_strict_round_trip_and_identity_are_declaration_order_neutral() -> None:
    original = specification()
    payload = json.loads(json.dumps(original.to_dict()))
    restored = OnlyResearchSpecification.from_dict(payload)
    reordered = OnlyResearchSpecification(
        original.dataset_snapshot_fingerprint,
        tuple(reversed(original.calculations)),
        tuple(reversed(original.statistics)),
    )
    assert restored == original
    assert restored.specification_fingerprint == original.specification_fingerprint
    assert reordered.specification_fingerprint == original.specification_fingerprint
    assert original.specification_fingerprint == "305323bea3a87e7d4fb864ac2915675858aa2a6529a4e82b1a230fd9e971cd80"


@pytest.mark.parametrize("version", [0, 2, "1", True, None])
def test_schema_version_and_unknown_fields_fail_closed(version: object) -> None:
    payload = dict(specification().to_dict())
    payload["schema_version"] = version
    with pytest.raises(OnlyResearchSpecificationError):
        OnlyResearchSpecification.from_dict(payload)
    payload = dict(specification().to_dict())
    payload["unknown"] = "forbidden"
    with pytest.raises(OnlyResearchSpecificationError):
        OnlyResearchSpecification.from_dict(payload)


def test_typed_scalar_round_trip_preserves_null_bool_integer_decimal_and_string() -> None:
    template = OnlyResearchGraphTemplate(
        (
            OnlyResearchGraphTemplateNode(
                "node",
                reference(OnlyCalculationKind.INDICATOR, "onlyalpha.indicator.ema"),
                {"null": None, "bool": True, "integer": 1, "decimal": Decimal("1.0"), "string": "1"},
            ),
        )
    )
    calc = OnlyResearchCalculationSpec("typed", template)
    restored = OnlyResearchCalculationSpec.from_dict(json.loads(json.dumps(calc.to_dict())))
    values = restored.graph_template.nodes[0].parameters
    assert tuple(type(values[name]) for name in ("null", "bool", "integer", "decimal", "string")) == (
        type(None),
        bool,
        int,
        Decimal,
        str,
    )


def test_symbolic_id_changes_request_identity_but_not_resolved_semantics() -> None:
    first = specification()
    second = OnlyResearchSpecification(
        first.dataset_snapshot_fingerprint,
        tuple(
            OnlyResearchCalculationSpec(
                "candidate" if item.calculation_id == "feature" else item.calculation_id, item.graph_template
            )
            for item in first.calculations
        ),
        tuple(
            type(item)(
                type(item.feature)("candidate", item.feature.template_node_id, item.feature.output_name),
                item.target,
                item.definition,
            )
            for item in first.statistics
        ),
    )
    from onlyalpha.research import OnlyResearchSpecificationResolver

    left = OnlyResearchSpecificationResolver(registry()).resolve(first)
    right = OnlyResearchSpecificationResolver(registry()).resolve(second)
    assert first.specification_fingerprint != second.specification_fingerprint
    assert [item.graph_fingerprint for item in left.candidates] == [item.graph_fingerprint for item in right.candidates]
    assert left.workload.result_plan.fingerprint == right.workload.result_plan.fingerprint


def test_dataset_bound_calculation_identity_and_runtime_neutral_graph_identity() -> None:
    from onlyalpha.research import OnlyResearchSpecificationResolver

    left = OnlyResearchSpecificationResolver(registry()).resolve(specification("a" * 64))
    right = OnlyResearchSpecificationResolver(registry()).resolve(specification("b" * 64))
    assert [item.graph_fingerprint for item in left.candidates] == [item.graph_fingerprint for item in right.candidates]
    assert [item.calculation_fingerprint for item in left.candidates] != [
        item.calculation_fingerprint for item in right.candidates
    ]


def test_duplicate_calculation_id_fails_closed() -> None:
    calc = OnlyResearchCalculationSpec("same", factor_template())
    base = specification()
    with pytest.raises(OnlyResearchSpecificationError) as error:
        OnlyResearchSpecification(base.dataset_snapshot_fingerprint, (calc, calc), base.statistics)
    assert error.value.code == "RESEARCH_SPEC_DUPLICATE_CALCULATION_ID"


def test_fresh_process_resolution_is_hash_seed_independent() -> None:
    program = (
        "import json; from tests.research.specification.support import registry,specification; "
        "from onlyalpha.research import OnlyResearchSpecificationResolver; "
        "s=specification(); r=OnlyResearchSpecificationResolver(registry()).resolve(s); "
        "print(json.dumps({'spec':r.specification_fingerprint,"
        "'graphs':[x.graph_fingerprint for x in r.candidates],"
        "'calculations':[x.calculation_fingerprint for x in r.candidates],"
        "'statistics':[x.statistics_fingerprint for x in r.statistics],"
        "'result':r.workload.result_plan.fingerprint},sort_keys=True))"
    )
    outputs = []
    for seed in ("1", "99"):
        outputs.append(
            subprocess.check_output(
                [sys.executable, "-c", program], text=True, env=dict(os.environ, PYTHONHASHSEED=seed)
            ).strip()
        )
    assert outputs[0] == outputs[1]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["calculations"][0].update({"unknown": True}),
        lambda payload: payload["calculations"][0].update({"sweep_dimensions": {}}),
        lambda payload: payload["calculations"][0].update({"graph_template": []}),
        lambda payload: payload["statistics"][0].update({"expansion": 1}),
        lambda payload: payload["statistics"][0]["feature"].update({"unknown": True}),
        lambda payload: payload["statistics"][0].update({"feature": []}),
    ],
)
def test_nested_schema_corruption_maps_to_specification_error(mutation) -> None:
    payload = json.loads(json.dumps(specification().to_dict()))
    mutation(payload)
    with pytest.raises(OnlyResearchSpecificationError) as error:
        OnlyResearchSpecification.from_dict(payload)
    assert error.value.phase.value == "SCHEMA"


def test_model_constructors_reject_invalid_structural_values() -> None:
    from onlyalpha.research import (
        OnlyResearchSeriesSelector,
        OnlyResearchStatisticsDefinition,
        OnlyResearchStatisticsMethod,
        OnlyResearchStatisticsSpec,
    )

    with pytest.raises(ValueError):
        OnlyResearchSeriesSelector("bad id", "node", "output")
    with pytest.raises(ValueError):
        OnlyResearchCalculationSpec("calc", object())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        OnlyResearchCalculationSpec("calc", factor_template(), [])  # type: ignore[arg-type]
    dimension = OnlyResearchSweepParameterDimension(OnlyResearchSweepParameterTarget("short", "period"), (1,))
    with pytest.raises(ValueError):
        OnlyResearchCalculationSpec("calc", factor_template(), (dimension, dimension))
    selector = OnlyResearchSeriesSelector("calc", "node", "output")
    definition = OnlyResearchStatisticsDefinition(method=OnlyResearchStatisticsMethod.IC)
    with pytest.raises(ValueError):
        OnlyResearchStatisticsSpec(object(), selector, definition)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        OnlyResearchStatisticsSpec(selector, selector, object())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        OnlyResearchStatisticsSpec(selector, selector, definition, "CARTESIAN")  # type: ignore[arg-type]
    with pytest.raises(OnlyResearchSpecificationError):
        OnlyResearchSpecification("a" * 64, (), ())
    with pytest.raises(OnlyResearchSpecificationError):
        OnlyResearchSpecification(
            "a" * 64,
            (OnlyResearchCalculationSpec("calc", factor_template()),),
            (),
        )
