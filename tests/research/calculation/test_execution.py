from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from decimal import Decimal

import pyarrow as pa
import pytest
from onlyalpha_plugin_indicators.registration import TYPES, registrations, resolve_definition

from onlyalpha.calculation import (
    OnlyCalculationBackendKind,
    OnlyCalculationBackendRegistration,
    OnlyCalculationGraphDefinition,
    OnlyCalculationNodeDefinition,
    OnlyCalculationReference,
    OnlyCalculationRegistry,
)
from onlyalpha.research.calculation import (
    OnlyResearchCalculationBackendResolver,
    OnlyResearchCalculationError,
    OnlyResearchCalculationExecutor,
)
from onlyalpha.research.dataset import OnlyParquetResearchDatasetSnapshotStore
from tests.research.calculation.support import reordered_snapshot, snapshot


def _registry() -> OnlyCalculationRegistry:
    registry = OnlyCalculationRegistry()
    for registration in registrations():
        registry.register(registration)
    return registry


def _graph():
    definition = resolve_definition(TYPES[0], {"period": 2})
    return OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(definition),))


def test_verified_dataset_execution_is_instrument_isolated_and_canonical(tmp_path) -> None:
    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    first, partitions = snapshot()
    committed = store.commit(first, partitions)
    execution = OnlyResearchCalculationExecutor(store, OnlyResearchCalculationBackendResolver(_registry())).execute(
        committed.snapshot_fingerprint, _graph()
    )
    assert tuple(item.instrument_id for item in execution.outputs) == ("A.XNAS", "B.XNAS")
    assert execution.outputs[0].table.column("ts_event_ns").to_pylist() == [
        int(item.ts_event.timestamp() * 1_000_000_000)
        for item in sorted(
            (bar for bar in partitions[0] if str(bar.instrument_id) == "A.XNAS"), key=lambda bar: bar.ts_event
        )
    ]
    assert execution.outputs[0].table.column("value").to_pylist() == [
        Decimal("1.000000000000"),
        Decimal("1.666666666667"),
        Decimal("3.222222222222"),
        Decimal("6.407407407407"),
    ]
    second_store = OnlyParquetResearchDatasetSnapshotStore(tmp_path / "other")
    second, second_partitions = reordered_snapshot()
    second_store.commit(second, second_partitions)
    repeated = OnlyResearchCalculationExecutor(
        second_store, OnlyResearchCalculationBackendResolver(_registry())
    ).execute(second.snapshot_fingerprint, _graph())
    assert repeated.calculation_fingerprint == execution.calculation_fingerprint
    assert [item.table.to_pydict() for item in repeated.outputs] == [
        item.table.to_pydict() for item in execution.outputs
    ]


def test_execution_refuses_tampered_dataset(tmp_path) -> None:
    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    candidate, partitions = snapshot()
    committed = store.commit(candidate, partitions)
    path = tmp_path / "sha256" / committed.snapshot_fingerprint[:2] / committed.snapshot_fingerprint
    partition = path / committed.partitions[0].relative_path
    partition.write_bytes(partition.read_bytes() + b"tamper")
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_DATASET_VERIFICATION_FAILED"):
        OnlyResearchCalculationExecutor(store, OnlyResearchCalculationBackendResolver(_registry())).execute(
            committed.snapshot_fingerprint, _graph()
        )


@pytest.mark.parametrize(
    ("mutation", "requested_fingerprint"),
    (
        (lambda payload: payload.update({"unknown": True}), None),
        (lambda payload: payload.update({"dataset_schema_fingerprint": "0" * 64}), None),
        (lambda payload: payload.update({"snapshot_fingerprint": "0" * 64}), None),
        (lambda payload: None, "0" * 64),
    ),
)
def test_execution_refuses_manifest_schema_and_identity_corruption(tmp_path, mutation, requested_fingerprint) -> None:
    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    candidate, partitions = snapshot()
    committed = store.commit(candidate, partitions)
    root = tmp_path / "sha256" / committed.snapshot_fingerprint[:2] / committed.snapshot_fingerprint
    manifest = root / "manifest.json"
    payload = json.loads(manifest.read_text())
    mutation(payload)
    manifest.write_text(json.dumps(payload))
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_DATASET_VERIFICATION_FAILED"):
        OnlyResearchCalculationExecutor(store, OnlyResearchCalculationBackendResolver(_registry())).execute(
            requested_fingerprint or committed.snapshot_fingerprint, _graph()
        )


class _PassBackend:
    def execute(self, definition, inputs):
        return {"value": pa.array(inputs["value"].to_pylist(), type=pa.decimal128(38, 18))}


def test_multi_node_dag_routes_dependency_and_order_is_stable(tmp_path) -> None:
    first = resolve_definition(TYPES[0], {"period": 2})
    derived_type = replace(
        TYPES[0],
        type_id="vendor.indicator.derived",
        inputs=(replace(TYPES[0].inputs[0], nullable=True),),
    )
    derived = derived_type.resolve(
        {"period": 2},
        {"value": OnlyCalculationReference(first.fingerprint, "value")},
        first.warmup,
    )
    registry = _registry()
    registry.register(
        OnlyCalculationBackendRegistration(derived_type, OnlyCalculationBackendKind.RESEARCH, _PassBackend())
    )
    graph = OnlyCalculationGraphDefinition(
        (OnlyCalculationNodeDefinition(derived), OnlyCalculationNodeDefinition(first))
    )
    reversed_graph = OnlyCalculationGraphDefinition(tuple(reversed(graph.nodes)))
    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    candidate, partitions = snapshot()
    store.commit(candidate, partitions)
    executor = OnlyResearchCalculationExecutor(store, OnlyResearchCalculationBackendResolver(registry))
    left = executor.execute(candidate.snapshot_fingerprint, graph)
    right = executor.execute(candidate.snapshot_fingerprint, reversed_graph)
    assert graph.fingerprint == reversed_graph.fingerprint
    assert left.calculation_fingerprint == right.calculation_fingerprint
    assert [item.node_fingerprint for item in left.outputs[:2]] == [first.fingerprint, derived.fingerprint]


class _InvalidBackend:
    def __init__(self, result):
        self.result = result

    def execute(self, definition, inputs):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.mark.parametrize(
    ("result", "message"),
    (({}, "output names"), ({"value": pa.array([1])}, "row count"), ({"value": pa.array([1, 2, 3, 4])}, "data_type")),
)
def test_invalid_backend_output_fails_whole_execution(tmp_path, result, message) -> None:
    definition = resolve_definition(TYPES[0], {"period": 2})
    registry = OnlyCalculationRegistry()
    registry.register(
        OnlyCalculationBackendRegistration(TYPES[0], OnlyCalculationBackendKind.RESEARCH, _InvalidBackend(result))
    )
    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    candidate, partitions = snapshot()
    store.commit(candidate, partitions)
    with pytest.raises(OnlyResearchCalculationError, match=message):
        OnlyResearchCalculationExecutor(store, OnlyResearchCalculationBackendResolver(registry)).execute(
            candidate.snapshot_fingerprint,
            OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(definition),)),
        )


def test_backend_failure_is_atomic(tmp_path) -> None:
    definition = resolve_definition(TYPES[0], {"period": 2})
    registry = OnlyCalculationRegistry()
    registry.register(
        OnlyCalculationBackendRegistration(
            TYPES[0], OnlyCalculationBackendKind.RESEARCH, _InvalidBackend(ValueError("injected"))
        )
    )
    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    candidate, partitions = snapshot()
    store.commit(candidate, partitions)
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_FAILED"):
        OnlyResearchCalculationExecutor(store, OnlyResearchCalculationBackendResolver(registry)).execute(
            candidate.snapshot_fingerprint,
            OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(definition),)),
        )


def test_identity_and_canonical_outputs_are_deterministic_in_fresh_process(tmp_path) -> None:
    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    candidate, partitions = snapshot()
    store.commit(candidate, partitions)
    code = (
        "import json,sys; "
        "from pathlib import Path; "
        "from onlyalpha.calculation import OnlyCalculationGraphDefinition,OnlyCalculationNodeDefinition,OnlyCalculationRegistry; "
        "from onlyalpha.research import OnlyParquetResearchDatasetSnapshotStore,OnlyResearchCalculationBackendResolver,OnlyResearchCalculationExecutor; "
        "from onlyalpha_plugin_indicators.registration import TYPES,registrations,resolve_definition; "
        "r=OnlyCalculationRegistry(); [r.register(x) for x in registrations()]; "
        "d=resolve_definition(TYPES[0],{'period':2}); g=OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(d),)); "
        "e=OnlyResearchCalculationExecutor(OnlyParquetResearchDatasetSnapshotStore(Path(sys.argv[1])),OnlyResearchCalculationBackendResolver(r)).execute(sys.argv[2],g); "
        "print(json.dumps({'fingerprint':e.calculation_fingerprint,'outputs':[x.table.to_pydict() for x in e.outputs]},default=str,sort_keys=True))"
    )
    values = [
        json.loads(
            subprocess.check_output(
                [sys.executable, "-c", code, str(tmp_path), candidate.snapshot_fingerprint], text=True
            )
        )
        for _ in range(2)
    ]
    assert values[0] == values[1]
