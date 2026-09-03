from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from decimal import Decimal

import pytest
from onlyalpha_example_alpha.registration import resolve_momentum
from onlyalpha_plugin_indicators.registration import TYPES, resolve_definition
from onlyalpha_plugin_operators.registration import resolve_cross_section_percentile

from onlyalpha.calculation import (
    OnlyCalculationBackendKind,
    OnlyCalculationBackendRegistration,
    OnlyCalculationDataType,
    OnlyCalculationGraphDefinition,
    OnlyCalculationKind,
    OnlyCalculationNodeDefinition,
    OnlyCalculationReference,
    OnlyCalculationRegistry,
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
from onlyalpha.research import (
    OnlyResearchGraphTemplate,
    OnlyResearchGraphTemplateNode,
    OnlyResearchSweepDefinition,
    OnlyResearchSweepError,
    OnlyResearchSweepParameterDimension,
    OnlyResearchSweepParameterTarget,
    OnlyResearchSweepPlanner,
)
from onlyalpha.research.calculation.identity import only_research_calculation_fingerprint
from tests.research.sweep.support import definition, factor_template, reference, registry


def _node(plan, cell: int, type_id: str):
    return next(
        item.definition for item in plan.cells[cell].calculation_graph.nodes if item.definition.type_id == type_id
    )


def test_period_and_price_field_rematerialize_warmup_source_and_all_identities() -> None:
    ema = next(item for item in TYPES if item.type_id == "onlyalpha.indicator.ema")
    template = OnlyResearchGraphTemplate(
        (OnlyResearchGraphTemplateNode("ema", reference(OnlyCalculationKind.INDICATOR, ema.type_id)),)
    )
    sweep = OnlyResearchSweepDefinition(
        "a" * 64,
        template,
        (
            OnlyResearchSweepParameterDimension(OnlyResearchSweepParameterTarget("ema", "period"), (20, 5)),
            OnlyResearchSweepParameterDimension(
                OnlyResearchSweepParameterTarget("ema", "price_field"), ("volume", "CLOSE")
            ),
        ),
    )
    plan = OnlyResearchSweepPlanner(registry()).plan(sweep)
    semantics = {
        (
            node.parameters["period"],
            node.parameters["price_field"],
            node.warmup.minimum_observations,
            node.input_bindings["value"].source,
        )
        for cell in plan.cells
        for node in (cell.calculation_graph.nodes[0].definition,)
    }
    assert semantics == {
        (5, "CLOSE", 5, "bar.close"),
        (5, "VOLUME", 5, "bar.volume"),
        (20, "CLOSE", 20, "bar.close"),
        (20, "VOLUME", 20, "bar.volume"),
    }
    assert len({cell.calculation_graph.fingerprint for cell in plan.cells}) == 4
    assert len({cell.calculation_fingerprint for cell in plan.cells}) == 4


def test_explicit_indicator_source_conflict_fails_closed() -> None:
    ema = next(item for item in TYPES if item.type_id == "onlyalpha.indicator.ema")
    from onlyalpha.research import OnlyResearchTemplateInputBinding, OnlyResearchTemplateReference

    template = OnlyResearchGraphTemplate(
        (
            OnlyResearchGraphTemplateNode(
                "ema",
                reference(OnlyCalculationKind.INDICATOR, ema.type_id),
                {"price_field": "VOLUME"},
                (OnlyResearchTemplateInputBinding("value", OnlyResearchTemplateReference(None, "value", "bar.close")),),
            ),
        )
    )
    with pytest.raises(OnlyResearchSweepError, match="conflict"):
        OnlyResearchSweepPlanner(registry()).plan(
            OnlyResearchSweepDefinition(
                "a" * 64,
                template,
                (OnlyResearchSweepParameterDimension(OnlyResearchSweepParameterTarget("ema", "period"), (5,)),),
            )
        )


def test_macd_constraints_and_derived_warmup_are_reapplied() -> None:
    macd = next(item for item in TYPES if item.type_id == "onlyalpha.indicator.macd")
    template = OnlyResearchGraphTemplate(
        (
            OnlyResearchGraphTemplateNode(
                "macd",
                reference(OnlyCalculationKind.INDICATOR, macd.type_id),
                {"fast_period": 3, "signal_period": 2},
            ),
        )
    )
    valid = OnlyResearchSweepDefinition(
        "a" * 64,
        template,
        (OnlyResearchSweepParameterDimension(OnlyResearchSweepParameterTarget("macd", "slow_period"), (8, 5)),),
    )
    plan = OnlyResearchSweepPlanner(registry()).plan(valid)
    assert {
        (
            cell.calculation_graph.nodes[0].definition.parameters["slow_period"],
            cell.calculation_graph.nodes[0].definition.warmup.minimum_observations,
        )
        for cell in plan.cells
    } == {(5, 6), (8, 9)}
    invalid = OnlyResearchSweepDefinition(
        "a" * 64,
        template,
        (OnlyResearchSweepParameterDimension(OnlyResearchSweepParameterTarget("macd", "slow_period"), (2,)),),
    )
    with pytest.raises(OnlyResearchSweepError, match="fast_period"):
        OnlyResearchSweepPlanner(registry()).plan(invalid)


def test_upstream_identity_propagates_while_independent_node_is_stable() -> None:
    plan = OnlyResearchSweepPlanner(registry()).plan(definition(candidates=(1, 3)))
    short = [_node(plan, index, "onlyalpha.indicator.rolling_return") for index in range(2)]
    # Each graph has two nodes of this type; locate the swept one by period.
    swept = [
        next(
            node.definition
            for node in cell.calculation_graph.nodes
            if node.definition.type_id.endswith("rolling_return") and node.definition.parameters["period"] != 2
        )
        for cell in plan.cells
    ]
    independent = [
        next(
            node.definition
            for node in cell.calculation_graph.nodes
            if node.definition.type_id.endswith("rolling_return") and node.definition.parameters["period"] == 2
        )
        for cell in plan.cells
    ]
    momentum = [_node(plan, index, "example.factor.momentum") for index in range(2)]
    score = [_node(plan, index, "onlyalpha.operator.cross_section_percentile") for index in range(2)]
    assert swept[0].fingerprint != swept[1].fingerprint
    assert independent[0].fingerprint == independent[1].fingerprint
    assert momentum[0].fingerprint != momentum[1].fingerprint
    assert score[0].fingerprint != score[1].fingerprint
    assert plan.cells[0].calculation_graph.fingerprint != plan.cells[1].calculation_graph.fingerprint
    assert short  # keep the exact type lookup exercised


def test_base_candidate_reproduces_existing_factor_graph_and_calculation_identity() -> None:
    rolling = next(item for item in TYPES if item.type_id == "onlyalpha.indicator.rolling_return")
    short = resolve_definition(rolling, {"period": 1})
    long = resolve_definition(rolling, {"period": 2})
    momentum = resolve_momentum(
        {"short_weight": Decimal("0.5"), "long_weight": Decimal("0.5")},
        OnlyCalculationReference(short.fingerprint, "value"),
        OnlyCalculationReference(long.fingerprint, "value"),
    )
    score = resolve_cross_section_percentile(
        {"direction": "HIGHER_IS_BETTER"}, OnlyCalculationReference(short.fingerprint, "value")
    )
    baseline = OnlyCalculationGraphDefinition(
        tuple(OnlyCalculationNodeDefinition(item) for item in (score, momentum, long, short))
    )
    cell = OnlyResearchSweepPlanner(registry()).plan(definition(candidates=(1,))).cells[0]
    assert cell.calculation_graph.fingerprint == baseline.fingerprint
    assert cell.calculation_fingerprint == only_research_calculation_fingerprint("a" * 64, baseline.fingerprint)


def test_dimension_candidate_mapping_order_alias_and_hash_seed_are_neutral() -> None:
    first = OnlyResearchSweepPlanner(registry()).plan(definition(candidates=(20, 5, 10)))
    second = OnlyResearchSweepPlanner(registry()).plan(
        OnlyResearchSweepDefinition(
            "a" * 64,
            factor_template(alias="presentation-only"),
            (OnlyResearchSweepParameterDimension(OnlyResearchSweepParameterTarget("short", "period"), (10, 20, 5)),),
        )
    )
    assert [cell.assignment_by_key for cell in first.cells] == [cell.assignment_by_key for cell in second.cells]
    assert [cell.calculation_fingerprint for cell in first.cells] == [
        cell.calculation_fingerprint for cell in second.cells
    ]
    code = (
        "import json; from tests.research.sweep.support import definition,registry; "
        "from onlyalpha.research import OnlyResearchSweepPlanner; p=OnlyResearchSweepPlanner(registry()).plan(definition(candidates=(20,5,10))); "
        "print(json.dumps([(dict(c.assignment_by_key),c.calculation_graph.fingerprint,c.calculation_fingerprint) for c in p.cells],sort_keys=True))"
    )
    outputs = []
    for seed in ("1", "99"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        outputs.append(subprocess.check_output([sys.executable, "-c", code], text=True, env=env).strip())
    assert outputs[0] == outputs[1]
    assert json.loads(outputs[0])


def test_cardinality_limit_is_operational_and_duplicate_materialized_cell_fails_closed() -> None:
    with pytest.raises(OnlyResearchSweepError) as exceeded:
        OnlyResearchSweepPlanner(registry(), max_cells=2).plan(definition(candidates=(1, 2, 3)))
    assert exceeded.value.code == "SWEEP_CARDINALITY_EXCEEDED"
    # The resolver canonicalizes enum case, so case variants are caught before materialization.
    direction = OnlyResearchSweepDefinition(
        "a" * 64,
        factor_template(),
        (
            OnlyResearchSweepParameterDimension(
                OnlyResearchSweepParameterTarget("score", "direction"),
                ("higher_is_better", "HIGHER_IS_BETTER"),
            ),
        ),
    )
    with pytest.raises(OnlyResearchSweepError) as duplicate:
        OnlyResearchSweepPlanner(registry()).plan(direction)
    assert duplicate.value.code == "SWEEP_DUPLICATE_PARAMETER_VALUE"


def test_distinct_assignments_with_same_materialized_calculation_fail_closed() -> None:
    type_definition = OnlyCalculationTypeDefinition(
        OnlyCalculationKind.INDICATOR,
        "test.indicator.canonicalized",
        "1",
        OnlyParameterSchema((OnlyParameterDefinition("value", OnlyParameterType.INTEGER, True),)),
        (OnlyInputDefinition("value", OnlyCalculationDataType.DECIMAL),),
        (OnlyOutputDefinition("value", OnlyCalculationDataType.DECIMAL, True),),
        OnlyMissingValuePolicy.FAIL,
        OnlyTimestampSemantic.EVENT_TIME,
        OnlyNumericDefinition(),
    )

    @dataclass(frozen=True)
    class _CanonicalizingResolver:
        type_definition: OnlyCalculationTypeDefinition

        def resolve(self, parameters, input_bindings):
            return self.type_definition.resolve(
                {"value": int(parameters["value"]) % 2},
                {"value": OnlyCalculationReference(None, "value", "bar.close")},
                OnlyWarmupDefinition(1, "ready", OnlyPreReadyOutput.PARTIAL, "fixed"),
            )

    local = OnlyCalculationRegistry()
    resolver = _CanonicalizingResolver(type_definition)
    local.register(
        OnlyCalculationBackendRegistration(
            type_definition,
            OnlyCalculationBackendKind.RESEARCH,
            object(),
            resolver,
        )
    )
    template = OnlyResearchGraphTemplate(
        (OnlyResearchGraphTemplateNode("node", reference(OnlyCalculationKind.INDICATOR, type_definition.type_id)),)
    )
    sweep = OnlyResearchSweepDefinition(
        "a" * 64,
        template,
        (OnlyResearchSweepParameterDimension(OnlyResearchSweepParameterTarget("node", "value"), (1, 3)),),
    )
    with pytest.raises(OnlyResearchSweepError) as duplicate:
        OnlyResearchSweepPlanner(local).plan(sweep)
    assert duplicate.value.code == "SWEEP_DUPLICATE_CELL"
    assert duplicate.value.ordinal == 1


def test_materializer_rejects_invalid_constructor_template_and_resolution() -> None:
    from onlyalpha.research import OnlyResearchGraphTemplateMaterializer

    with pytest.raises(TypeError):
        OnlyResearchGraphTemplateMaterializer(object())  # type: ignore[arg-type]
    materializer = OnlyResearchGraphTemplateMaterializer(registry())
    with pytest.raises(OnlyResearchSweepError) as invalid:
        materializer.materialize(object())  # type: ignore[arg-type]
    assert invalid.value.code == "SWEEP_TEMPLATE_INVALID"
