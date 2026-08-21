from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, replace
from decimal import Decimal

import pytest

from onlyalpha.calculation import OnlyCalculationDataType, OnlyCalculationKind, OnlyCalculationTypeReference
from onlyalpha.research import (
    OnlyParquetResearchDatasetSnapshotStore,
    OnlyResearchCalculationBackendResolver,
    OnlyResearchCalculationExecutor,
    OnlyResearchComparison,
    OnlyResearchComparisonOperator,
    OnlyResearchDatasetFieldRef,
    OnlyResearchDefinitionError,
    OnlyResearchDefinitionResolver,
    OnlyResearchFixedParameter,
    OnlyResearchSpecification,
    OnlyResearchSpecificationError,
    OnlyResearchSpecificationResolver,
    OnlyResearchSweepParameter,
    OnlyResearchTypedLiteral,
    OnlyResearchVariableRef,
)
from tests.research.calculation.support import snapshot
from tests.research.definition.support import definition
from tests.research.evaluation.support import evaluation_registry


@dataclass
class _Datasets:
    store: OnlyParquetResearchDatasetSnapshotStore
    fingerprint: str

    def resolve_verified(self, expected):
        verified = self.store.load_verified_table(self.fingerprint)
        if verified.snapshot.definition != expected:
            raise ValueError("Dataset Definition is not available")
        return verified


def _case(tmp_path):
    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path / "datasets")
    candidate, partitions = snapshot()
    committed = store.commit(candidate, partitions)
    registry = evaluation_registry()
    resolver = OnlyResearchDefinitionResolver(registry, _Datasets(store, committed.snapshot_fingerprint))
    return committed, store, registry, resolver


def test_global_candidates_role_terminals_and_existing_specification_equivalence(tmp_path) -> None:
    committed, _, registry, resolver = _case(tmp_path)
    result = resolver.resolve(definition(committed.definition))
    assert len(result.candidates) == 4
    assert len({item.candidate_fingerprint for item in result.candidates}) == 4
    assert [dict(item.assignment) for item in result.candidates] == [
        {"returns_short.period": 1, "rsi.period": 14},
        {"returns_short.period": 1, "rsi.period": 7},
        {"returns_short.period": 2, "rsi.period": 14},
        {"returns_short.period": 2, "rsi.period": 7},
    ]
    type_ids = {node.type_reference.type_id for node in result.decision_graph_template.nodes}
    assert "onlyalpha.predicate.internal.terminal.eligibility" in type_ids
    assert "onlyalpha.predicate.internal.terminal.entry_signal" in type_ids
    assert "onlyalpha.predicate.internal.terminal.exit_signal" in type_ids
    for lineage in (item for item in result.specification_resolution.candidates if item.calculation_id == "decision"):
        predicate_dependencies = {
            reference.node_fingerprint
            for node in lineage.graph.nodes
            if node.definition.kind is OnlyCalculationKind.PREDICATE
            for reference in node.definition.input_bindings.values()
            if reference.node_fingerprint is not None
        }
        assert lineage.node_fingerprints["rsi"] in predicate_dependencies
        assert lineage.node_fingerprints["momentum"] in predicate_dependencies

    manual_exact_specification = OnlyResearchSpecification(
        result.dataset_snapshot_fingerprint,
        tuple(result.specification.calculations),
        tuple(result.specification.statistics),
        result.specification.evidence,
        result.specification.schema_version,
    )
    manual = OnlyResearchSpecificationResolver(registry).resolve(manual_exact_specification)
    assert result.specification == manual_exact_specification
    assert result.workload == manual.workload
    assert result.specification_fingerprint == manual.specification_fingerprint


def test_specification_v2_publication_and_candidate_identity_survive_fresh_resolution(tmp_path) -> None:
    committed, _, _, resolver = _case(tmp_path)
    base = definition(committed.definition)
    first = resolver.resolve(base)
    rsi = next(item for item in base.calculations if item.instance_key == "rsi")
    expanded = resolver.resolve(
        replace(
            base,
            calculations=tuple(
                replace(item, published_outputs=("value", "zone")) if item is rsi else item
                for item in base.calculations
            ),
        )
    )
    assert [item.calculation_fingerprint for item in first.candidates] == [
        item.calculation_fingerprint for item in expanded.candidates
    ]
    assert first.specification_fingerprint != expanded.specification_fingerprint
    assert [item.candidate_fingerprint for item in first.candidates] != [
        item.candidate_fingerprint for item in expanded.candidates
    ]
    serialized = json.loads(json.dumps(first.specification.to_dict()))
    restored = OnlyResearchSpecification.from_dict(serialized)
    fresh = OnlyResearchSpecificationResolver(evaluation_registry()).resolve(restored)
    assert [item.candidate_fingerprint for item in fresh.candidates if item.candidate_fingerprint] == [
        item.candidate_fingerprint for item in first.specification_resolution.candidates if item.candidate_fingerprint
    ]
    assert fresh.published_series == first.specification_resolution.published_series
    assert fresh.signals == first.specification_resolution.signals
    specification_path = tmp_path / "specification-v2.json"
    specification_path.write_text(json.dumps(serialized), encoding="utf-8")
    program = (
        "import json,sys; from onlyalpha.research import OnlyResearchSpecification,OnlyResearchSpecificationResolver; "
        "from tests.research.evaluation.support import evaluation_registry; "
        "p=json.load(open(sys.argv[1],encoding='utf-8')); "
        "r=OnlyResearchSpecificationResolver(evaluation_registry()).resolve(OnlyResearchSpecification.from_dict(p)); "
        "print(json.dumps([x.candidate_fingerprint for x in r.candidates if x.candidate_fingerprint]))"
    )
    reconstructed = json.loads(
        subprocess.check_output([sys.executable, "-c", program, str(specification_path)], text=True)
    )
    assert reconstructed == [
        item.candidate_fingerprint for item in first.specification_resolution.candidates if item.candidate_fingerprint
    ]


def test_predicate_generic_publication_fails_while_signal_evidence_remains_admitted(tmp_path) -> None:
    committed, _, registry, resolver = _case(tmp_path)
    resolved = resolver.resolve(definition(committed.definition))
    evidence = resolved.specification.evidence
    assert evidence is not None
    assert evidence.signals.eligibility is not None
    assert evidence.signals.entry is not None
    assert evidence.signals.exit is not None
    assert {item.role for item in resolved.specification_resolution.signals} == {
        "ELIGIBILITY",
        "ENTRY_SIGNAL",
        "EXIT_SIGNAL",
    }

    predicate_selector = evidence.signals.entry
    invalid_evidence = replace(evidence, published_series=(*evidence.published_series, predicate_selector))
    invalid = replace(resolved.specification, evidence=invalid_evidence)
    with pytest.raises(OnlyResearchSpecificationError) as error:
        OnlyResearchSpecificationResolver(registry).resolve(invalid)

    assert error.value.code == "RESEARCH_SPEC_PUBLISHED_SERIES_KIND_FORBIDDEN"


def test_candidate_graph_executes_boolean_series_without_eligibility_rewriting_entry(tmp_path) -> None:
    committed, store, registry, resolver = _case(tmp_path)
    base = definition(committed.definition)
    independent_entry = OnlyResearchComparison(
        OnlyResearchComparisonOperator.LT,
        OnlyResearchDatasetFieldRef("close"),
        OnlyResearchTypedLiteral(OnlyCalculationDataType.DECIMAL, Decimal("5")),
    )
    result = resolver.resolve(replace(base, signals=replace(base.signals, entry=independent_entry)))
    graph = result.specification_resolution.candidates[0].graph
    execution = OnlyResearchCalculationExecutor(store, OnlyResearchCalculationBackendResolver(registry)).execute(
        committed.snapshot_fingerprint, graph
    )
    definitions = {node.fingerprint: node.definition for node in graph.nodes}
    outputs = {
        (definitions[item.node_fingerprint].outputs[0].semantic_type, item.instrument_id): item.table.column(
            "value"
        ).to_pylist()
        for item in execution.outputs
        if definitions[item.node_fingerprint].kind.value == "PREDICATE"
        and definitions[item.node_fingerprint].type_id.startswith("onlyalpha.predicate.internal.terminal")
    }
    assert {role for role, _ in outputs} == {"ELIGIBILITY", "ENTRY_SIGNAL", "EXIT_SIGNAL"}
    assert all(isinstance(value, (bool, type(None))) for series in outputs.values() for value in series)
    assert any(
        eligibility is False and entry is True
        for role, instrument in outputs
        if role == "ELIGIBILITY"
        for eligibility, entry in zip(
            outputs[("ELIGIBILITY", instrument)], outputs[("ENTRY_SIGNAL", instrument)], strict=True
        )
    )


def test_candidate_cardinality_and_target_sweep_fail_before_execution(tmp_path) -> None:
    committed, store, _, _ = _case(tmp_path)
    small = OnlyResearchDefinitionResolver(
        evaluation_registry(),
        _Datasets(OnlyParquetResearchDatasetSnapshotStore(tmp_path / "datasets"), committed.snapshot_fingerprint),
        max_candidates=3,
    )
    with pytest.raises(OnlyResearchDefinitionError) as error:
        small.resolve(definition(committed.definition))
    assert error.value.code == "RESEARCH_DEFINITION_CANDIDATE_CARDINALITY_EXCEEDED"

    base = definition(committed.definition)
    swept_target = replace(
        base.targets[0],
        parameters={"exit_offset": OnlyResearchSweepParameter((1, 2))},
    )
    with pytest.raises(OnlyResearchDefinitionError) as target_error:
        OnlyResearchDefinitionResolver(evaluation_registry(), _Datasets(store, committed.snapshot_fingerprint)).resolve(
            replace(base, targets=(swept_target,))
        )
    assert target_error.value.code == "RESEARCH_DEFINITION_TARGET_SWEEP_FORBIDDEN"


def test_unpublished_output_and_duplicate_normalized_sweep_fail_closed(tmp_path) -> None:
    committed, _, _, resolver = _case(tmp_path)
    base = definition(committed.definition)
    hidden = replace(
        base.statistics[0],
        variable=OnlyResearchVariableRef("rsi", "zone"),
    )
    with pytest.raises(OnlyResearchDefinitionError) as unpublished:
        resolver.resolve(replace(base, statistics=(hidden,)))
    assert unpublished.value.code == "RESEARCH_DEFINITION_STATISTICS_VARIABLE_UNPUBLISHED"

    rsi = next(item for item in base.calculations if item.instance_key == "rsi")
    duplicate = replace(rsi, parameters={"period": OnlyResearchSweepParameter((1, "1"))})
    with pytest.raises(OnlyResearchDefinitionError) as normalized:
        resolver.resolve(
            replace(base, calculations=tuple(duplicate if item is rsi else item for item in base.calculations))
        )
    assert normalized.value.code == "RESEARCH_DEFINITION_SWEEP_DUPLICATE"


@pytest.mark.parametrize(
    ("mutator", "code"),
    (
        (
            lambda base: replace(
                base,
                calculations=(
                    replace(
                        base.calculations[0],
                        type_reference=OnlyCalculationTypeReference(
                            OnlyCalculationKind.INDICATOR, "onlyalpha.indicator.unknown", "1"
                        ),
                    ),
                    *base.calculations[1:],
                ),
            ),
            "RESEARCH_DEFINITION_CALCULATION_UNKNOWN",
        ),
        (
            lambda base: replace(
                base,
                calculations=(
                    replace(
                        base.calculations[0],
                        type_reference=OnlyCalculationTypeReference(
                            OnlyCalculationKind.INDICATOR, "onlyalpha.indicator.rsi", "999"
                        ),
                    ),
                    *base.calculations[1:],
                ),
            ),
            "RESEARCH_DEFINITION_CALCULATION_VERSION_UNKNOWN",
        ),
        (
            lambda base: replace(
                base,
                calculations=(replace(base.targets[0], instance_key="future_in_decision"), *base.calculations[1:]),
            ),
            "RESEARCH_DEFINITION_CALCULATION_KIND_INVALID",
        ),
        (
            lambda base: replace(
                base,
                calculations=(
                    replace(base.calculations[0], parameters={"unknown": OnlyResearchSweepParameter((1, 2))}),
                    *base.calculations[1:],
                ),
            ),
            "RESEARCH_DEFINITION_PARAMETER_INVALID",
        ),
        (
            lambda base: replace(
                base,
                calculations=(
                    replace(base.calculations[0], parameters={"period": OnlyResearchSweepParameter((1, "bad"))}),
                    *base.calculations[1:],
                ),
            ),
            "RESEARCH_DEFINITION_PARAMETER_INVALID",
        ),
        (
            lambda base: replace(
                base,
                calculations=(
                    replace(base.calculations[0], parameters={"period": OnlyResearchSweepParameter((0, 1))}),
                    *base.calculations[1:],
                ),
            ),
            "RESEARCH_DEFINITION_PARAMETER_INVALID",
        ),
        (
            lambda base: replace(
                base,
                calculations=(replace(base.calculations[0], published_outputs=("missing",)), *base.calculations[1:]),
            ),
            "RESEARCH_DEFINITION_OUTPUT_UNKNOWN",
        ),
    ),
)
def test_calculation_admission_is_strict(tmp_path, mutator, code) -> None:
    committed, _, _, resolver = _case(tmp_path)
    with pytest.raises(OnlyResearchDefinitionError) as error:
        resolver.resolve(mutator(definition(committed.definition)))
    assert error.value.code == code


def test_expression_target_causality_and_statistics_compatibility_fail_closed(tmp_path) -> None:
    committed, _, _, resolver = _case(tmp_path)
    base = definition(committed.definition)
    future_entry = OnlyResearchComparison(
        OnlyResearchComparisonOperator.GT,
        OnlyResearchVariableRef("forward_return_1", "target_value"),
        OnlyResearchTypedLiteral(OnlyCalculationDataType.DECIMAL, Decimal("0")),
    )
    with pytest.raises(OnlyResearchDefinitionError) as future:
        resolver.resolve(replace(base, signals=replace(base.signals, entry=future_entry)))
    assert future.value.code == "RESEARCH_DEFINITION_VARIABLE_UNPUBLISHED"

    incompatible = replace(base.statistics[0], variable=OnlyResearchVariableRef("rsi", "value"))
    with pytest.raises(OnlyResearchDefinitionError) as statistics:
        resolver.resolve(replace(base, statistics=(incompatible,)))
    assert statistics.value.code == "RESEARCH_DEFINITION_STATISTICS_INCOMPATIBLE"


def test_resolution_is_deterministic_and_multiple_explicit_targets_are_admitted(tmp_path) -> None:
    committed, _, _, resolver = _case(tmp_path)
    base = definition(committed.definition)
    second_target = replace(
        base.targets[0],
        instance_key="forward_return_2",
        parameters={"exit_offset": OnlyResearchFixedParameter(2)},
    )
    extended = replace(base, targets=(*base.targets, second_target))
    first = resolver.resolve(extended)
    second = resolver.resolve(extended)
    assert first == second
    assert len(first.resolved_targets) == 2
