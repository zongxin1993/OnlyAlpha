from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

import pyarrow as pa  # type: ignore[import-untyped]
import pytest

from onlyalpha.calculation import (
    OnlyCalculationBackendKind,
    OnlyCalculationDataType,
    OnlyCalculationKind,
    OnlyCalculationReference,
    OnlyCalculationTypeDefinition,
    OnlyCalculationTypeReference,
    OnlyMissingValuePolicy,
    OnlyNumericDefinition,
    OnlyOutputDefinition,
    OnlyParameterSchema,
    OnlyPreReadyOutput,
    OnlyTimestampSemantic,
    OnlyWarmupDefinition,
)
from onlyalpha.calculation.registry import OnlyCalculationBackendRegistration, OnlyCalculationRegistry
from onlyalpha.domain.value import OnlyQuantity
from onlyalpha.research import (
    OnlyResearchAnd,
    OnlyResearchCalculationBackendResolver,
    OnlyResearchCalculationInstance,
    OnlyResearchCalculationSpec,
    OnlyResearchComparison,
    OnlyResearchComparisonOperator,
    OnlyResearchDatasetFieldRef,
    OnlyResearchDefinitionError,
    OnlyResearchDefinitionResolver,
    OnlyResearchFixedParameter,
    OnlyResearchGraphTemplate,
    OnlyResearchGraphTemplateNode,
    OnlyResearchOr,
    OnlyResearchSeriesSelector,
    OnlyResearchSpecification,
    OnlyResearchSpecificationResolver,
    OnlyResearchStatisticsSpec,
    OnlyResearchSweepParameter,
    OnlyResearchSweepParameterDimension,
    OnlyResearchSweepParameterTarget,
    OnlyResearchTemplateInputBinding,
    OnlyResearchTemplateReference,
    OnlyResearchTypedLiteral,
    OnlyResearchVariableRef,
    only_canonicalize_research_expression,
    only_register_research_predicate_primitives,
    only_research_expression_fingerprint,
    only_research_predicate_type_reference,
)
from onlyalpha.research.definition.resolver import _ExpressionLowerer
from tests.research.calculation.support import bars, snapshot
from tests.research.definition.support import definition
from tests.research.definition.test_resolution import _case, _Datasets
from tests.research.evaluation.support import evaluation_registry


def test_authoring_and_resolved_identity_are_distinct_and_normalization_stable(tmp_path) -> None:
    committed, _, _, resolver = _case(tmp_path)
    base = definition(committed.definition)
    rsi = next(item for item in base.calculations if item.instance_key == "rsi")
    textual = replace(rsi, parameters={"period": OnlyResearchSweepParameter(("14", "7"))})
    returns_long = next(item for item in base.calculations if item.instance_key == "returns_long")
    textual_fixed = replace(returns_long, parameters={"period": OnlyResearchFixedParameter("3")})
    alternate = replace(
        base,
        calculations=tuple(
            textual if item.instance_key == "rsi" else textual_fixed if item.instance_key == "returns_long" else item
            for item in base.calculations
        ),
        display_metadata={"name": "Alpha B"},
    )

    assert base.definition_fingerprint != alternate.definition_fingerprint
    first = resolver.resolve(base)
    second = resolver.resolve(alternate)
    assert first.authoring_definition_fingerprint == base.definition_fingerprint
    assert second.authoring_definition_fingerprint == alternate.definition_fingerprint
    assert first.resolved_definition_fingerprint == second.resolved_definition_fingerprint
    assert [item.candidate_fingerprint for item in first.candidates] == [
        item.candidate_fingerprint for item in second.candidates
    ]
    assert first.specification_fingerprint == second.specification_fingerprint
    assert first.workload == second.workload
    metadata_only = resolver.resolve(replace(base, display_metadata={"name": "Alpha C"}))
    assert metadata_only.resolved_definition_fingerprint == first.resolved_definition_fingerprint

    reversed_sweeps = resolver.resolve(definition(committed.definition, reverse_sweeps=True))
    assert reversed_sweeps.resolved_definition_fingerprint == first.resolved_definition_fingerprint
    assert reversed_sweeps.candidates == first.candidates


def test_resolved_identity_changes_for_semantics_and_exact_dataset_snapshot(tmp_path) -> None:
    committed, store, registry, resolver = _case(tmp_path)
    base = definition(committed.definition)
    returns_long = next(item for item in base.calculations if item.instance_key == "returns_long")
    changed = replace(returns_long, parameters={"period": OnlyResearchFixedParameter(4)})
    semantic = replace(
        base,
        calculations=tuple(changed if item.instance_key == "returns_long" else item for item in base.calculations),
    )
    assert (
        resolver.resolve(base).resolved_definition_fingerprint
        != resolver.resolve(semantic).resolved_definition_fingerprint
    )

    alternate_bars = list(bars())
    alternate_bars[0] = replace(alternate_bars[0], volume=OnlyQuantity(Decimal("999"), 0))
    alternate_candidate, alternate_partitions = snapshot(tuple(alternate_bars))
    alternate_snapshot = store.commit(alternate_candidate, alternate_partitions)
    alternate = OnlyResearchDefinitionResolver(registry, _Datasets(store, alternate_snapshot.snapshot_fingerprint))
    assert (
        resolver.resolve(base).resolved_definition_fingerprint
        != alternate.resolve(base).resolved_definition_fingerprint
    )


def test_dataset_calculation_sources_require_canonical_spelling(tmp_path) -> None:
    committed, _, _, resolver = _case(tmp_path)
    base = definition(committed.definition)

    first = resolver.resolve(base)
    second = resolver.resolve(base)
    assert first.resolved_definition_fingerprint == second.resolved_definition_fingerprint

    target = base.targets[0]
    aliased_inputs = tuple(
        replace(item, source="close") if item.input_name == "entry_price" else item for item in target.input_bindings
    )
    invalid = replace(base, targets=(replace(target, input_bindings=aliased_inputs),))
    with pytest.raises(OnlyResearchDefinitionError) as error:
        resolver.resolve(invalid)
    assert (error.value.code, error.value.path) == (
        "RESEARCH_DEFINITION_DATASET_FIELD_UNKNOWN",
        "targets[forward_return_1].input_bindings[entry_price].source",
    )


def test_commutative_identity_preserves_authoring_structure_and_exact_workload(tmp_path) -> None:
    committed, _, _, resolver = _case(tmp_path)
    base = definition(committed.definition)
    assert isinstance(base.signals.entry, OnlyResearchAnd)
    reversed_entry = OnlyResearchAnd(tuple(reversed(base.signals.entry.operands)))
    reversed_definition = replace(base, signals=replace(base.signals, entry=reversed_entry))

    assert base.signals.entry.operands != reversed_definition.signals.entry.operands
    assert base.to_dict()["signals"] != reversed_definition.to_dict()["signals"]
    assert base.definition_fingerprint == reversed_definition.definition_fingerprint

    first = resolver.resolve(base)
    second = resolver.resolve(reversed_definition)
    assert first.resolved_definition_fingerprint == second.resolved_definition_fingerprint
    assert first.decision_graph_template == second.decision_graph_template
    assert first.specification_fingerprint == second.specification_fingerprint
    assert first.workload == second.workload


def test_diagnostics_validate_authoring_order_before_canonical_lowering(tmp_path) -> None:
    committed, _, _, resolver = _case(tmp_path)
    base = definition(committed.definition)
    valid = OnlyResearchComparison(
        OnlyResearchComparisonOperator.LT,
        OnlyResearchVariableRef("rsi", "value"),
        OnlyResearchTypedLiteral(OnlyCalculationDataType.DECIMAL, Decimal("30")),
    )
    invalid = OnlyResearchComparison(
        OnlyResearchComparisonOperator.GT,
        OnlyResearchVariableRef("returns_long", "value"),
        OnlyResearchTypedLiteral(OnlyCalculationDataType.STRING, "bad"),
    )
    authored = OnlyResearchAnd((valid, invalid))
    canonical = only_canonicalize_research_expression(authored)
    assert isinstance(canonical, OnlyResearchAnd)
    assert canonical.operands == (invalid, valid)

    with pytest.raises(OnlyResearchDefinitionError) as error:
        resolver.resolve(replace(base, signals=replace(base.signals, entry=authored)))
    assert (error.value.code, error.value.path) == (
        "RESEARCH_DEFINITION_COMPARISON_TYPE_INVALID",
        "signals.entry.operands[1].right",
    )


def test_nested_diagnostic_path_preserves_submitted_operand_positions(tmp_path) -> None:
    committed, _, _, resolver = _case(tmp_path)
    base = definition(committed.definition)
    valid = OnlyResearchComparison(
        OnlyResearchComparisonOperator.GT,
        OnlyResearchDatasetFieldRef("close"),
        OnlyResearchTypedLiteral(OnlyCalculationDataType.DECIMAL, Decimal("1")),
    )
    invalid = OnlyResearchComparison(
        OnlyResearchComparisonOperator.GT,
        OnlyResearchVariableRef("returns_long", "value"),
        OnlyResearchTypedLiteral(OnlyCalculationDataType.STRING, "bad"),
    )
    authored = OnlyResearchAnd((valid, OnlyResearchOr((valid, invalid))))

    with pytest.raises(OnlyResearchDefinitionError) as error:
        resolver.resolve(replace(base, signals=replace(base.signals, entry=authored)))
    assert (error.value.code, error.value.path) == (
        "RESEARCH_DEFINITION_COMPARISON_TYPE_INVALID",
        "signals.entry.operands[1].operands[1].right",
    )


def test_failed_expression_validation_has_no_graph_side_effects() -> None:
    nodes = {}
    lowerer = _ExpressionLowerer({}, nodes)
    invalid = OnlyResearchComparison(
        OnlyResearchComparisonOperator.GT,
        OnlyResearchDatasetFieldRef("close"),
        OnlyResearchTypedLiteral(OnlyCalculationDataType.STRING, "bad"),
    )

    with pytest.raises(OnlyResearchDefinitionError):
        lowerer.lower_terminal("entry_signal", invalid, "signals.entry")
    assert nodes == {}


@pytest.mark.parametrize(
    ("role", "expression", "code", "path"),
    (
        (
            "entry",
            OnlyResearchAnd(
                (
                    OnlyResearchComparison(
                        OnlyResearchComparisonOperator.GT,
                        OnlyResearchDatasetFieldRef("close"),
                        OnlyResearchTypedLiteral(OnlyCalculationDataType.DECIMAL, Decimal("1")),
                    ),
                    OnlyResearchComparison(
                        OnlyResearchComparisonOperator.GT,
                        OnlyResearchDatasetFieldRef("close"),
                        OnlyResearchTypedLiteral(OnlyCalculationDataType.STRING, "bad"),
                    ),
                )
            ),
            "RESEARCH_DEFINITION_COMPARISON_TYPE_INVALID",
            "signals.entry.operands[1].right",
        ),
        (
            "exit",
            OnlyResearchComparison(
                OnlyResearchComparisonOperator.EQ,
                OnlyResearchVariableRef("unknown", "value"),
                OnlyResearchTypedLiteral(OnlyCalculationDataType.DECIMAL, Decimal("0")),
            ),
            "RESEARCH_DEFINITION_VARIABLE_UNPUBLISHED",
            "signals.exit.left",
        ),
        (
            "eligibility",
            OnlyResearchComparison(
                OnlyResearchComparisonOperator.GT,
                OnlyResearchDatasetFieldRef("close"),
                OnlyResearchDatasetFieldRef("unknown"),
            ),
            "RESEARCH_DEFINITION_DATASET_FIELD_UNKNOWN",
            "eligibility.right",
        ),
    ),
)
def test_expression_diagnostics_use_exact_definition_paths(tmp_path, role, expression, code, path) -> None:
    committed, _, _, resolver = _case(tmp_path)
    base = definition(committed.definition)
    if role == "entry":
        invalid = replace(base, signals=replace(base.signals, entry=expression))
    elif role == "exit":
        invalid = replace(base, signals=replace(base.signals, exit=expression))
    else:
        invalid = replace(base, eligibility=expression)
    with pytest.raises(OnlyResearchDefinitionError) as error:
        resolver.resolve(invalid)
    assert (error.value.code, error.value.path) == (code, path)


def _predicate_backend(name: str, inputs: dict[str, pa.Array], parameters: dict[str, object] | None = None):
    registry = OnlyCalculationRegistry()
    only_register_research_predicate_primitives(registry)
    reference = only_research_predicate_type_reference(name)
    bindings = {input_name: OnlyCalculationReference(None, input_name, "bar.close") for input_name in inputs}
    definition_ = registry.rematerialize_definition(reference, parameters or {}, bindings)
    backend = OnlyResearchCalculationBackendResolver(registry).resolve(definition_)
    return backend.execute(definition_, inputs)["value"].to_pylist()


def test_predicate_backend_freezes_three_valued_boolean_truth_tables() -> None:
    left = pa.array([True, True, False, False, None, None], type=pa.bool_())
    right = pa.array([True, None, False, None, True, None], type=pa.bool_())
    assert _predicate_backend("boolean.and", {"left": left, "right": right}) == [
        True,
        None,
        False,
        False,
        None,
        None,
    ]
    assert _predicate_backend("boolean.or", {"left": left, "right": right}) == [
        True,
        True,
        False,
        None,
        True,
        None,
    ]
    assert _predicate_backend("boolean.not", {"value": pa.array([True, False, None])}) == [False, True, None]


def test_predicate_backend_preserves_null_comparisons_and_all_terminal_roles() -> None:
    left = pa.array([Decimal("1"), None, Decimal("3")], type=pa.decimal128(38, 12))
    right = pa.array([Decimal("2"), Decimal("2"), None], type=pa.decimal128(38, 12))
    assert _predicate_backend("compare.lt.decimal.refs", {"left": left, "right": right}) == [True, None, None]
    assert _predicate_backend(
        "compare.eq.string.refs",
        {"left": pa.array(["a", "b", None]), "right": pa.array(["a", "c", "a"])},
    ) == [True, False, None]
    assert _predicate_backend(
        "compare.eq.boolean.refs",
        {"left": pa.array([True, False, None]), "right": pa.array([True, True, False])},
    ) == [True, False, None]
    values = pa.array([True, False, None], type=pa.bool_())
    for role in ("eligibility", "entry_signal", "exit_signal"):
        assert _predicate_backend(f"terminal.{role}", {"value": values}) == [True, False, None]


def test_comparison_admission_accepts_numeric_refs_and_rejects_string_ordering(tmp_path) -> None:
    committed, _, _, resolver = _case(tmp_path)
    base = definition(committed.definition)
    numeric_refs = OnlyResearchComparison(
        OnlyResearchComparisonOperator.GT,
        OnlyResearchDatasetFieldRef("close"),
        OnlyResearchVariableRef("rsi", "value"),
    )
    resolver.resolve(replace(base, eligibility=numeric_refs))

    rsi = next(item for item in base.calculations if item.instance_key == "rsi")
    with_zone = replace(rsi, published_outputs=("value", "zone"))
    string_ordering = OnlyResearchComparison(
        OnlyResearchComparisonOperator.GT,
        OnlyResearchVariableRef("rsi", "zone"),
        OnlyResearchTypedLiteral(OnlyCalculationDataType.STRING, "LOW"),
    )
    invalid = replace(
        base,
        calculations=tuple(with_zone if item.instance_key == "rsi" else item for item in base.calculations),
        signals=replace(base.signals, exit=string_ordering),
    )
    with pytest.raises(OnlyResearchDefinitionError) as error:
        resolver.resolve(invalid)
    assert (error.value.code, error.value.path) == (
        "RESEARCH_DEFINITION_COMPARISON_TYPE_INVALID",
        "signals.exit.right",
    )


@dataclass(frozen=True)
class _TestDefinitionResolver:
    type_definition: OnlyCalculationTypeDefinition

    def resolve(self, parameters, input_bindings):
        return self.type_definition.resolve(
            parameters,
            input_bindings,
            OnlyWarmupDefinition(1, "test source is available", OnlyPreReadyOutput.NULL, "UPSTREAM"),
        )


def _register_test_series(registry, key: str, output: OnlyOutputDefinition) -> OnlyResearchCalculationInstance:
    type_definition = OnlyCalculationTypeDefinition(
        OnlyCalculationKind.INDICATOR,
        f"tests.definition.{key}",
        "1",
        OnlyParameterSchema(),
        (),
        (output,),
        OnlyMissingValuePolicy.PROPAGATE,
        OnlyTimestampSemantic.EVENT_TIME,
        OnlyNumericDefinition(),
    )
    registry.register(
        OnlyCalculationBackendRegistration(
            type_definition,
            OnlyCalculationBackendKind.RESEARCH,
            object(),
            _TestDefinitionResolver(type_definition),
        )
    )
    return OnlyResearchCalculationInstance(
        key,
        OnlyCalculationTypeReference(type_definition.kind, type_definition.type_id, type_definition.semantic_version),
        {},
        ("value",),
    )


@pytest.mark.parametrize(
    ("left_output", "right_output", "reason"),
    (
        (
            OnlyOutputDefinition("value", OnlyCalculationDataType.DECIMAL, True, unit="USD"),
            OnlyOutputDefinition("value", OnlyCalculationDataType.DECIMAL, True, unit="EUR"),
            "unit",
        ),
        (
            OnlyOutputDefinition("value", OnlyCalculationDataType.DECIMAL, True, dimensions=("TIME",)),
            OnlyOutputDefinition("value", OnlyCalculationDataType.DECIMAL, True, dimensions=("ASSET", "TIME")),
            "dimensions",
        ),
    ),
)
def test_series_comparison_fails_closed_on_authoritative_metadata(tmp_path, left_output, right_output, reason) -> None:
    committed, store, _, _ = _case(tmp_path)
    registry = evaluation_registry()
    left = _register_test_series(registry, "left_series", left_output)
    right = _register_test_series(registry, "right_series", right_output)
    resolver = OnlyResearchDefinitionResolver(registry, _Datasets(store, committed.snapshot_fingerprint))
    base = definition(committed.definition)
    comparison = OnlyResearchComparison(
        OnlyResearchComparisonOperator.EQ,
        OnlyResearchVariableRef("left_series", "value"),
        OnlyResearchVariableRef("right_series", "value"),
    )
    invalid = replace(base, calculations=(*base.calculations, left, right), eligibility=comparison)
    with pytest.raises(OnlyResearchDefinitionError) as error:
        resolver.resolve(invalid)
    assert (error.value.code, error.value.path, error.value.detail) == (
        "RESEARCH_DEFINITION_COMPARISON_INCOMPATIBLE",
        "eligibility.right",
        f"series {reason} are incompatible",
    )


def _ref(node: str | None, output: str, source: str | None = None) -> OnlyResearchTemplateReference:
    return OnlyResearchTemplateReference(node, output, source)


def _binding(name: str, node: str | None, output: str, source: str | None = None):
    return OnlyResearchTemplateInputBinding(name, _ref(node, output, source))


def _comparison_node(expression: OnlyResearchComparison) -> OnlyResearchGraphTemplateNode:
    node_id = f"predicate_{only_research_expression_fingerprint(expression)}"
    data_type = (
        expression.left.data_type
        if isinstance(expression.left, OnlyResearchTypedLiteral)
        else OnlyCalculationDataType.DECIMAL
    )
    literal = expression.left if isinstance(expression.left, OnlyResearchTypedLiteral) else expression.right
    reference = expression.right if isinstance(expression.left, OnlyResearchTypedLiteral) else expression.left
    operator = {"<": "lt", ">": "gt"}[expression.operator.value]
    if isinstance(reference, OnlyResearchDatasetFieldRef):
        binding = _binding("left", None, "left", f"bar.{reference.field_name}")
    else:
        binding = _binding("left", reference.instance_key, reference.output_name)
    return OnlyResearchGraphTemplateNode(
        node_id,
        only_research_predicate_type_reference(f"compare.{operator}.{data_type.value.lower()}.literal"),
        {"literal": literal.value, "literal_left": isinstance(expression.left, OnlyResearchTypedLiteral)},
        (binding,),
    )


def _independent_specification(base, snapshot_fingerprint: str) -> OnlyResearchSpecification:
    calculations = {item.instance_key: item for item in base.calculations}
    eligibility = base.eligibility
    entry = base.signals.entry
    exit_expression = base.signals.exit
    assert isinstance(eligibility, OnlyResearchComparison)
    assert isinstance(entry, OnlyResearchAnd)
    assert isinstance(exit_expression, OnlyResearchComparison)
    entry_parts = tuple(entry.operands)
    comparison_nodes = tuple(_comparison_node(item) for item in (eligibility, *entry_parts, exit_expression))
    entry_id = f"predicate_{only_research_expression_fingerprint(entry)}"
    nodes = (
        OnlyResearchGraphTemplateNode(
            "rsi", calculations["rsi"].type_reference, {"period": 14, "price_field": "CLOSE"}
        ),
        OnlyResearchGraphTemplateNode(
            "returns_short",
            calculations["returns_short"].type_reference,
            {"period": 1, "price_field": "CLOSE"},
        ),
        OnlyResearchGraphTemplateNode(
            "returns_long", calculations["returns_long"].type_reference, {"period": 3, "price_field": "CLOSE"}
        ),
        OnlyResearchGraphTemplateNode(
            "momentum",
            calculations["momentum"].type_reference,
            {"long_weight": Decimal("0.5"), "short_weight": Decimal("0.5")},
            (
                _binding("return_long", "returns_long", "value"),
                _binding("return_short", "returns_short", "value"),
            ),
        ),
        *comparison_nodes,
        OnlyResearchGraphTemplateNode(
            entry_id,
            only_research_predicate_type_reference("boolean.and"),
            {},
            (
                _binding("left", f"predicate_{only_research_expression_fingerprint(entry_parts[0])}", "value"),
                _binding("right", f"predicate_{only_research_expression_fingerprint(entry_parts[1])}", "value"),
            ),
        ),
        OnlyResearchGraphTemplateNode(
            "eligibility_terminal",
            only_research_predicate_type_reference("terminal.eligibility"),
            {},
            (_binding("value", f"predicate_{only_research_expression_fingerprint(eligibility)}", "value"),),
        ),
        OnlyResearchGraphTemplateNode(
            "entry_signal_terminal",
            only_research_predicate_type_reference("terminal.entry_signal"),
            {},
            (_binding("value", entry_id, "value"),),
        ),
        OnlyResearchGraphTemplateNode(
            "exit_signal_terminal",
            only_research_predicate_type_reference("terminal.exit_signal"),
            {},
            (_binding("value", f"predicate_{only_research_expression_fingerprint(exit_expression)}", "value"),),
        ),
    )
    decision = OnlyResearchCalculationSpec(
        "decision",
        OnlyResearchGraphTemplate(nodes),
        (
            OnlyResearchSweepParameterDimension(OnlyResearchSweepParameterTarget("returns_short", "period"), (1, 2)),
            OnlyResearchSweepParameterDimension(OnlyResearchSweepParameterTarget("rsi", "period"), (7, 14)),
        ),
    )
    target = base.targets[0]
    target_spec = OnlyResearchCalculationSpec(
        "target.forward_return_1",
        OnlyResearchGraphTemplate(
            (
                OnlyResearchGraphTemplateNode(
                    "forward_return_1",
                    target.type_reference,
                    {"entry_offset": 0, "exit_offset": 1},
                    (
                        _binding("entry_price", None, "entry_price", "bar.close"),
                        _binding("exit_price", None, "exit_price", "bar.close"),
                    ),
                ),
            )
        ),
    )
    statistics = OnlyResearchStatisticsSpec(
        OnlyResearchSeriesSelector("decision", "momentum", "factor_value"),
        OnlyResearchSeriesSelector("target.forward_return_1", "forward_return_1", "target_value"),
        base.statistics[0].definition,
    )
    return OnlyResearchSpecification(snapshot_fingerprint, (decision, target_spec), (statistics,))


def test_definition_lowering_matches_independently_authored_exact_specification(tmp_path) -> None:
    committed, _, registry, resolver = _case(tmp_path)
    base = definition(committed.definition)
    generated = resolver.resolve(base)
    expected_v1 = _independent_specification(base, committed.snapshot_fingerprint)
    expected = OnlyResearchSpecification(
        expected_v1.dataset_snapshot_fingerprint,
        expected_v1.calculations,
        expected_v1.statistics,
        generated.specification.evidence,
        generated.specification.schema_version,
    )

    assert generated.specification == expected
    expected_resolution = OnlyResearchSpecificationResolver(registry).resolve(expected)
    assert generated.specification_fingerprint == expected_resolution.specification_fingerprint
    assert generated.specification_resolution.candidates == expected_resolution.candidates
    assert generated.specification_resolution.statistics == expected_resolution.statistics
    assert generated.workload == expected_resolution.workload
