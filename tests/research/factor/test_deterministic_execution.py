from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from decimal import Decimal

import pyarrow as pa
import pytest
from onlyalpha_example_alpha.registration import registrations as factor_registrations
from onlyalpha_plugin_indicators.registration import registrations as indicator_registrations
from onlyalpha_plugin_operators.registration import CROSS_SECTION_PERCENTILE
from onlyalpha_plugin_operators.registration import registrations as operator_registrations

from onlyalpha.calculation import (
    OnlyCalculationGraphDefinition,
    OnlyCalculationNodeDefinition,
    OnlyCalculationReference,
)
from onlyalpha.research import (
    OnlyResearchCalculationBackendResolver,
    OnlyResearchCalculationError,
    OnlyResearchCalculationExecutor,
    OnlyResearchJobDisposition,
    OnlyResearchJobError,
)
from onlyalpha.research.dataset import OnlyParquetResearchDatasetSnapshotStore, OnlyVerifiedResearchDataset
from tests.research.calculation.support import reordered_snapshot, snapshot
from tests.research.factor.support import factor_case, factor_graph, factor_registry
from tests.research.job.support import research_job_executor


class _StaticVerifiedStore:
    def __init__(self, verified: OnlyVerifiedResearchDataset) -> None:
        self.verified = verified

    def load_verified_table(self, snapshot_fingerprint: str) -> OnlyVerifiedResearchDataset:
        assert snapshot_fingerprint == self.verified.snapshot.snapshot_fingerprint
        return self.verified


def _outputs_by_type(execution, graph, type_id: str):
    fingerprint = next(node.fingerprint for node in graph.nodes if node.definition.type_id == type_id)
    return {item.instrument_id: item.table for item in execution.outputs if item.node_fingerprint == fingerprint}


def test_factor_graph_exposes_every_dependency_and_alias_is_not_identity() -> None:
    graph = factor_graph()
    ordered = graph.ordered_nodes
    assert tuple(node.definition.type_id for node in ordered) == (
        "onlyalpha.indicator.rolling_return",
        "onlyalpha.indicator.rolling_return",
        "example.factor.momentum",
        "onlyalpha.operator.cross_section_percentile",
    )
    momentum = ordered[2].definition
    scorer = ordered[3].definition
    assert {reference.node_fingerprint for reference in momentum.input_bindings.values()} == {
        ordered[0].fingerprint,
        ordered[1].fingerprint,
    }
    short = next(node for node in ordered if node.definition.parameters.get("period") == 1)
    assert scorer.input_bindings["value"].node_fingerprint == short.fingerprint
    aliased = OnlyCalculationGraphDefinition(
        tuple(OnlyCalculationNodeDefinition(node.definition, f"node-{index}") for index, node in enumerate(graph.nodes))
    )
    assert aliased.fingerprint == graph.fingerprint


def test_generic_operator_input_does_not_require_factor_semantic_type() -> None:
    graph = factor_graph()
    scorer = graph.ordered_nodes[-1].definition
    rebound = replace(
        scorer,
        input_bindings={"value": OnlyCalculationReference(graph.ordered_nodes[0].fingerprint, "value")},
    )
    generic = OnlyCalculationGraphDefinition(
        tuple(node for node in graph.nodes if node.fingerprint != scorer.fingerprint)
        + (OnlyCalculationNodeDefinition(rebound),)
    )
    assert generic.ordered_nodes[-1].definition.type_id == "onlyalpha.operator.cross_section_percentile"


def test_node_first_execution_produces_raw_values_and_cross_section_scores(tmp_path) -> None:
    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    candidate, partitions = snapshot()
    store.commit(candidate, partitions)
    graph = factor_graph()
    execution = OnlyResearchCalculationExecutor(
        store, OnlyResearchCalculationBackendResolver(factor_registry())
    ).execute(candidate.snapshot_fingerprint, graph)
    values = _outputs_by_type(execution, graph, "example.factor.momentum")
    scores = _outputs_by_type(execution, graph, "onlyalpha.operator.cross_section_percentile")
    assert values["A.XNAS"].column("factor_value").to_pylist() == [
        None,
        None,
        Decimal("2.000000000000"),
        Decimal("2.000000000000"),
    ]
    assert values["B.XNAS"].column("factor_value").to_pylist() == [
        None,
        None,
        Decimal("-0.155555555556"),
        Decimal("-0.173611111111"),
    ]
    assert scores["A.XNAS"].column("percentile").to_pylist() == [
        None,
        Decimal("1.000000000000"),
        Decimal("1.000000000000"),
        Decimal("1.000000000000"),
    ]
    assert scores["B.XNAS"].column("percentile").to_pylist() == [
        None,
        Decimal("0E-12"),
        Decimal("0E-12"),
        Decimal("0E-12"),
    ]
    assert tuple((item.instrument_id, item.node_fingerprint) for item in execution.outputs) == tuple(
        (instrument_id, node.fingerprint) for instrument_id in ("A.XNAS", "B.XNAS") for node in graph.ordered_nodes
    )


def test_semantic_result_is_independent_of_dataset_physical_order(tmp_path) -> None:
    graph = factor_graph()
    executions = []
    candidate, canonical_partitions = snapshot()
    cases = (
        snapshot(),
        reordered_snapshot(),
        (candidate, (canonical_partitions[0][:4], canonical_partitions[0][4:])),
    )
    for index, (candidate, partitions) in enumerate(cases):
        store = OnlyParquetResearchDatasetSnapshotStore(tmp_path / str(index))
        store.commit(candidate, partitions)
        executions.append(
            OnlyResearchCalculationExecutor(store, OnlyResearchCalculationBackendResolver(factor_registry())).execute(
                candidate.snapshot_fingerprint, graph
            )
        )
    assert executions[0].calculation_fingerprint == executions[1].calculation_fingerprint
    assert [output.table.to_pydict() for output in executions[0].outputs] == [
        output.table.to_pydict() for output in executions[1].outputs
    ]


def test_cross_section_requires_complete_exact_timestamp_axis(tmp_path) -> None:
    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    candidate, partitions = snapshot()
    committed = store.commit(candidate, partitions)
    verified = store.load_verified_table(committed.snapshot_fingerprint)
    rows = verified.table.to_pylist()
    rows.pop(0)
    malformed = OnlyVerifiedResearchDataset(verified.snapshot, pa.Table.from_pylist(rows, schema=verified.table.schema))
    executor = OnlyResearchCalculationExecutor(
        _StaticVerifiedStore(malformed), OnlyResearchCalculationBackendResolver(factor_registry())
    )
    with pytest.raises(OnlyResearchCalculationError) as raised:
        executor.execute(candidate.snapshot_fingerprint, factor_graph())
    assert raised.value.code == "RESEARCH_CROSS_SECTION_ALIGNMENT_FAILED"


def _registry_with_scorer(backend):
    registry = factor_registry().__class__()
    for registration in (*operator_registrations(), *indicator_registrations(), *factor_registrations()):
        registry.register(
            replace(registration, provider=backend)
            if registration.type_definition is CROSS_SECTION_PERCENTILE
            else registration
        )
    return registry


def test_operator_output_does_not_claim_factor_score_semantics() -> None:
    graph = factor_graph()
    scorer = next(
        node.definition
        for node in graph.nodes
        if node.definition.type_id == "onlyalpha.operator.cross_section_percentile"
    )
    assert scorer.inputs[0].semantic_type == "NUMERIC_SERIES"
    assert scorer.outputs[0].semantic_type == "NUMERIC_SERIES"


class _ChangingTypeBackend:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, definition, inputs):
        self.calls += 1
        scale = 12 if self.calls == 1 else 6
        return {"percentile": pa.array([Decimal("0.5")] * len(inputs["value"]), type=pa.decimal128(38, scale))}


class _StableResearchErrorBackend:
    def execute(self, definition, inputs):
        raise OnlyResearchCalculationError("RESEARCH_CROSS_SECTION_ALIGNMENT_FAILED", "backend detected alignment")


@pytest.mark.parametrize(
    ("backend", "code"),
    (
        (_ChangingTypeBackend(), "RESEARCH_OUTPUT_INVALID"),
        (_StableResearchErrorBackend(), "RESEARCH_CROSS_SECTION_ALIGNMENT_FAILED"),
    ),
)
def test_cross_section_backend_failures_remain_stable_and_atomic(tmp_path, backend, code) -> None:
    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    candidate, partitions = snapshot()
    store.commit(candidate, partitions)
    with pytest.raises(OnlyResearchCalculationError) as raised:
        OnlyResearchCalculationExecutor(
            store, OnlyResearchCalculationBackendResolver(_registry_with_scorer(backend))
        ).execute(candidate.snapshot_fingerprint, factor_graph())
    assert raised.value.code == code


def test_empty_cross_section_axis_fails_closed(tmp_path) -> None:
    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    candidate, partitions = snapshot()
    committed = store.commit(candidate, partitions)
    verified = store.load_verified_table(committed.snapshot_fingerprint)
    empty = OnlyVerifiedResearchDataset(verified.snapshot, verified.table.slice(0, 0))
    with pytest.raises(OnlyResearchCalculationError) as raised:
        OnlyResearchCalculationExecutor(
            _StaticVerifiedStore(empty), OnlyResearchCalculationBackendResolver(factor_registry())
        ).execute(candidate.snapshot_fingerprint, factor_graph())
    assert raised.value.code == "RESEARCH_CROSS_SECTION_ALIGNMENT_FAILED"


def test_factor_result_store_and_job_converge_to_one_verified_authority(tmp_path) -> None:
    plan, calculation, result_store, _job = factor_case(tmp_path)

    class _CountingCalculation:
        def __init__(self, delegate) -> None:
            self.delegate = delegate
            self.calls = 0

        def _execute_verified(self, snapshot_fingerprint, graph):
            self.calls += 1
            return self.delegate._execute_verified(snapshot_fingerprint, graph)

    counted = _CountingCalculation(calculation)
    job = research_job_executor(counted, result_store)
    first = job.execute(plan)
    second = job.execute(plan)
    assert first.disposition is OnlyResearchJobDisposition.EXECUTED
    assert second.disposition is OnlyResearchJobDisposition.REUSED
    assert first.calculation_fingerprint == second.calculation_fingerprint == plan.calculation_fingerprint
    assert first.calculation_result_fingerprint == second.calculation_result_fingerprint
    verified = result_store.load_verified(plan.calculation_fingerprint)
    assert verified.manifest.calculation_result_fingerprint == first.calculation_result_fingerprint
    assert len(verified.outputs) == 8
    assert counted.calls == 1


def test_factor_graph_result_and_reuse_identity_are_fresh_process_stable(tmp_path) -> None:
    plan, _calculation, _store, job = factor_case(tmp_path)
    executed = job.execute(plan)
    code = (
        "import json,sys; from pathlib import Path; "
        "from tests.research.factor.support import factor_case; "
        "p,c,s,j=factor_case(Path(sys.argv[1])); o=j.execute(p); "
        "print(json.dumps({'graph':p.calculation_graph.fingerprint,'calculation':o.calculation_fingerprint,"
        "'result':o.calculation_result_fingerprint,'disposition':o.disposition.value},sort_keys=True))"
    )
    observed = json.loads(subprocess.check_output([sys.executable, "-c", code, str(tmp_path)], text=True))
    assert observed == {
        "calculation": executed.calculation_fingerprint,
        "disposition": "REUSED",
        "graph": plan.calculation_graph.fingerprint,
        "result": executed.calculation_result_fingerprint,
    }


def test_corrupt_factor_result_fails_closed_without_reexecution(tmp_path) -> None:
    plan, calculation, _store, job = factor_case(tmp_path)
    job.execute(plan)
    root = tmp_path / "results" / "sha256" / plan.calculation_fingerprint[:2] / plan.calculation_fingerprint
    partition = next((root / "data").iterdir())
    partition.write_bytes(partition.read_bytes() + b"tamper")

    class _ForbiddenCalculation:
        def __init__(self) -> None:
            self.calls = 0

        def _execute_verified(self, snapshot_fingerprint, graph):
            self.calls += 1
            return calculation._execute_verified(snapshot_fingerprint, graph)

    forbidden = _ForbiddenCalculation()
    with pytest.raises(OnlyResearchJobError, match="RESULT_CORRUPT"):
        research_job_executor(forbidden, factor_case(tmp_path)[2]).execute(plan)
    assert forbidden.calls == 0
