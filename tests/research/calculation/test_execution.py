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
    OnlyCalculationTypeReference,
    OnlyTimestampSemantic,
    only_implementation_manifest_from_bytes,
)
from onlyalpha.research.calculation import (
    OnlyResearchCalculationBackendResolver,
    OnlyResearchCalculationError,
    OnlyResearchCalculationExecutor,
)
from onlyalpha.research.dataset import (
    OnlyParquetResearchDatasetSnapshotStore,
    OnlyVerifiedResearchDataset,
)
from tests.research.calculation.support import reordered_snapshot, snapshot


def _registry() -> OnlyCalculationRegistry:
    registry = OnlyCalculationRegistry()
    for registration in registrations():
        registry.register(registration)
    return registry


def _registration(type_definition, provider):
    manifest = only_implementation_manifest_from_bytes(
        calculation_type_reference=OnlyCalculationTypeReference(
            type_definition.kind, type_definition.type_id, type_definition.semantic_version
        ),
        backend_kind=OnlyCalculationBackendKind.RESEARCH,
        entrypoint_identity=f"{type(provider).__module__}:{type(provider).__qualname__}",
        resources={"backend.py": type(provider).__qualname__.encode()},
    )
    return OnlyCalculationBackendRegistration(
        type_definition,
        OnlyCalculationBackendKind.RESEARCH,
        provider,
        implementation_manifest=manifest,
    )


def _graph():
    definition = resolve_definition(TYPES[0], {"period": 2})
    return OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(definition),))


class _StaticVerifiedStore:
    def __init__(self, verified: OnlyVerifiedResearchDataset) -> None:
        self._verified = verified

    def load_verified_table(self, snapshot_fingerprint: str) -> OnlyVerifiedResearchDataset:
        assert snapshot_fingerprint == self._verified.snapshot.snapshot_fingerprint
        return self._verified


def _verified(tmp_path) -> tuple[OnlyVerifiedResearchDataset, OnlyCalculationRegistry]:
    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    candidate, partitions = snapshot()
    committed = store.commit(candidate, partitions)
    return store.load_verified_table(committed.snapshot_fingerprint), _registry()


def _execute_static(verified, registry, graph):
    return OnlyResearchCalculationExecutor(
        _StaticVerifiedStore(verified), OnlyResearchCalculationBackendResolver(registry)
    ).execute(verified.snapshot.snapshot_fingerprint, graph)


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


def test_process_reused_official_backend_has_no_cross_execution_state(tmp_path) -> None:
    verified, registry = _verified(tmp_path)
    resolver = OnlyResearchCalculationBackendResolver(registry)
    definition = _graph().nodes[0].definition
    provider = resolver.resolve(definition).provider
    executor = OnlyResearchCalculationExecutor(_StaticVerifiedStore(verified), resolver)

    first = executor.execute(verified.snapshot.snapshot_fingerprint, _graph())
    second = executor.execute(verified.snapshot.snapshot_fingerprint, _graph())

    assert resolver.resolve(definition).provider is provider
    assert [item.table.to_pydict() for item in first.outputs] == [item.table.to_pydict() for item in second.outputs]


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


def test_execution_rejects_unsupported_verified_dataset_schema(tmp_path) -> None:
    verified, registry = _verified(tmp_path)
    unsupported = OnlyVerifiedResearchDataset(replace(verified.snapshot, dataset_schema=object()), verified.table)
    with pytest.raises(OnlyResearchCalculationError) as raised:
        _execute_static(unsupported, registry, _graph())
    assert raised.value.code == "RESEARCH_INPUT_INCOMPATIBLE"
    assert raised.value.detail == "unsupported Dataset schema"


@pytest.mark.parametrize("mutation", ("out-of-order", "duplicate"))
def test_execution_rejects_noncanonical_instrument_event_rows(tmp_path, mutation: str) -> None:
    verified, registry = _verified(tmp_path)
    rows = verified.table.to_pylist()
    first_instrument = rows[0]["instrument_id"]
    indexes = [index for index, row in enumerate(rows) if row["instrument_id"] == first_instrument]
    if mutation == "out-of-order":
        rows[indexes[0]], rows[indexes[1]] = rows[indexes[1]], rows[indexes[0]]
    else:
        rows[indexes[1]]["ts_event_ns"] = rows[indexes[0]]["ts_event_ns"]
    malformed = OnlyVerifiedResearchDataset(verified.snapshot, pa.Table.from_pylist(rows, schema=verified.table.schema))
    with pytest.raises(OnlyResearchCalculationError) as raised:
        _execute_static(malformed, registry, _graph())
    assert raised.value.code == "RESEARCH_INPUT_INCOMPATIBLE"
    assert raised.value.detail == "instrument rows are not canonical"


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
    registry.register(_registration(derived_type, _PassBackend()))
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


def test_execution_plan_rejects_graph_node_binding_set_mismatch(tmp_path) -> None:
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
    valid_graph = OnlyCalculationGraphDefinition(
        (OnlyCalculationNodeDefinition(first), OnlyCalculationNodeDefinition(derived))
    )
    registry = _registry()
    registry.register(_registration(derived_type, _PassBackend()))
    verified, _ = _verified(tmp_path)

    class _InvalidExecutionOrder:
        fingerprint = valid_graph.fingerprint
        nodes = valid_graph.nodes
        ordered_nodes = (OnlyCalculationNodeDefinition(derived),)

    with pytest.raises(OnlyResearchCalculationError) as raised:
        _execute_static(verified, registry, _InvalidExecutionOrder())
    assert raised.value.code == "RESEARCH_IMPLEMENTATION_IDENTITY_UNRESOLVED"
    assert "node set differs" in raised.value.detail


class _InvalidBackend:
    def __init__(self, result):
        self.result = result

    def execute(self, definition, inputs):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.mark.parametrize(
    ("result", "message"),
    (
        ({}, "output names"),
        ({"value": pa.array([1])}, "row count"),
        ({"value": pa.array([1, 2, 3, 4])}, "data_type"),
    ),
)
def test_invalid_backend_output_fails_whole_execution(tmp_path, result, message) -> None:
    definition = resolve_definition(TYPES[0], {"period": 2})
    registry = OnlyCalculationRegistry()
    registry.register(_registration(TYPES[0], _InvalidBackend(result)))
    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    candidate, partitions = snapshot()
    store.commit(candidate, partitions)
    with pytest.raises(OnlyResearchCalculationError, match=message) as raised:
        OnlyResearchCalculationExecutor(store, OnlyResearchCalculationBackendResolver(registry)).execute(
            candidate.snapshot_fingerprint,
            OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(definition),)),
        )
    assert raised.value.code == "RESEARCH_OUTPUT_INVALID"


def test_non_nullable_backend_output_rejects_null_atomically(tmp_path) -> None:
    definition = resolve_definition(TYPES[0], {"period": 2})
    definition = replace(definition, outputs=(replace(definition.outputs[0], nullable=False),))
    result = {"value": pa.array([Decimal("1"), None, Decimal("3"), Decimal("4")], type=pa.decimal128(38, 18))}
    registry = OnlyCalculationRegistry()
    registry.register(_registration(TYPES[0], _InvalidBackend(result)))
    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    candidate, partitions = snapshot()
    store.commit(candidate, partitions)
    with pytest.raises(OnlyResearchCalculationError) as raised:
        OnlyResearchCalculationExecutor(store, OnlyResearchCalculationBackendResolver(registry)).execute(
            candidate.snapshot_fingerprint,
            OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(definition),)),
        )
    assert raised.value.code == "RESEARCH_OUTPUT_INVALID"
    assert raised.value.detail == "value nullability"


def test_execution_rejects_unsupported_timestamp_semantic(tmp_path) -> None:
    definition = replace(resolve_definition(TYPES[0], {"period": 2}), timestamp=OnlyTimestampSemantic.BAR_CLOSE)
    verified, registry = _verified(tmp_path)
    graph = OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(definition),))
    with pytest.raises(OnlyResearchCalculationError) as raised:
        _execute_static(verified, registry, graph)
    assert raised.value.code == "RESEARCH_OUTPUT_INVALID"
    assert raised.value.detail == "unsupported timestamp BAR_CLOSE"


def test_backend_failure_is_atomic(tmp_path) -> None:
    definition = resolve_definition(TYPES[0], {"period": 2})
    registry = OnlyCalculationRegistry()
    registry.register(_registration(TYPES[0], _InvalidBackend(ValueError("injected"))))
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
