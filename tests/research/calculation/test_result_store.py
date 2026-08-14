from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from onlyalpha_plugin_indicators.registration import TYPES, registrations, resolve_definition

from onlyalpha.calculation import (
    OnlyCalculationDataType,
    OnlyCalculationGraphDefinition,
    OnlyCalculationNodeDefinition,
    OnlyCalculationRegistry,
)
from onlyalpha.research.calculation import (
    OnlyParquetResearchCalculationResultStore,
    OnlyResearchCalculationBackendResolver,
    OnlyResearchCalculationExecution,
    OnlyResearchCalculationExecutor,
    OnlyResearchCalculationNodeOutput,
    OnlyResearchCalculationResultStoreError,
    only_research_calculation_fingerprint,
    only_research_calculation_partition_fingerprint,
    only_research_calculation_result_content_fingerprint,
    only_research_calculation_result_fingerprint,
)
from onlyalpha.research.dataset import OnlyParquetResearchDatasetSnapshotStore
from tests.research.calculation.support import snapshot

_AUDIT_TIME = datetime(2026, 8, 14, tzinfo=UTC)


def _registry() -> OnlyCalculationRegistry:
    registry = OnlyCalculationRegistry()
    for registration in registrations():
        registry.register(registration)
    return registry


def _graph() -> OnlyCalculationGraphDefinition:
    definition = resolve_definition(TYPES[0], {"period": 2})
    return OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(definition),))


def _case(tmp_path, *, result_root="results", compression="zstd", row_group_size=None):
    dataset_store = OnlyParquetResearchDatasetSnapshotStore(tmp_path / "datasets")
    candidate, partitions = snapshot()
    dataset_store.commit(candidate, partitions)
    graph = _graph()
    execution = OnlyResearchCalculationExecutor(
        dataset_store, OnlyResearchCalculationBackendResolver(_registry())
    ).execute(candidate.snapshot_fingerprint, graph)
    result_store = OnlyParquetResearchCalculationResultStore(
        tmp_path / result_root,
        dataset_store,
        compression=compression,
        row_group_size=row_group_size,
        audit_time=lambda: _AUDIT_TIME,
    )
    return dataset_store, result_store, graph, execution


def _root(store_root, calculation_fingerprint):
    return store_root / "sha256" / calculation_fingerprint[:2] / calculation_fingerprint


def _changed(execution: OnlyResearchCalculationExecution) -> OnlyResearchCalculationExecution:
    output = execution.outputs[0]
    table = output.table
    values = table.column("value").to_pylist()
    values[-1] = Decimal("999.000000000000")
    changed = table.set_column(
        table.schema.get_field_index("value"),
        "value",
        pa.array(values, type=table.column("value").type),
    )
    return replace(
        execution,
        outputs=(replace(output, table=changed), *execution.outputs[1:]),
    )


def test_identity_commit_verified_load_and_idempotency(tmp_path) -> None:
    _, store, graph, execution = _case(tmp_path)
    first = store.commit(execution, graph)
    second = store.commit(replace(execution, outputs=tuple(reversed(execution.outputs))), graph)
    loaded = store.load_verified(execution.calculation_fingerprint)
    assert first == second == loaded
    assert store.exists(execution.calculation_fingerprint)
    verification = store.verify(execution.calculation_fingerprint)
    assert verification.valid
    assert verification.calculation_result_fingerprint == first.manifest.calculation_result_fingerprint
    assert first.manifest.result_content_fingerprint != execution.calculation_fingerprint
    assert first.manifest.calculation_result_fingerprint == only_research_calculation_result_fingerprint(
        execution.calculation_fingerprint, first.manifest.result_content_fingerprint
    )
    assert [output.table.to_pydict() for output in loaded.outputs] == [
        output.table.to_pydict() for output in execution.outputs
    ]


def test_physical_options_and_root_do_not_change_semantic_result_identity(tmp_path) -> None:
    dataset_store, first_store, graph, execution = _case(tmp_path, row_group_size=1)
    first = first_store.commit(execution, graph)
    second_store = OnlyParquetResearchCalculationResultStore(
        tmp_path / "other-results",
        dataset_store,
        compression="snappy",
        row_group_size=100,
        audit_time=lambda: _AUDIT_TIME,
    )
    second = second_store.commit(execution, graph)
    assert first.manifest.result_content_fingerprint == second.manifest.result_content_fingerprint
    assert first.manifest.calculation_result_fingerprint == second.manifest.calculation_result_fingerprint
    assert [item.byte_sha256 for item in first.manifest.partitions] != [
        item.byte_sha256 for item in second.manifest.partitions
    ]


def test_partition_identity_binds_value_timestamp_instrument_and_node(tmp_path) -> None:
    _, _, _, execution = _case(tmp_path)
    output = execution.outputs[0]
    canonical = pa.Table.from_arrays(
        [output.table.column("ts_event_ns"), output.table.column("value")],
        schema=pa.schema(
            [
                pa.field("ts_event_ns", pa.int64(), False),
                pa.field("value", output.table.column("value").type, True),
            ]
        ),
    )
    fingerprint = only_research_calculation_partition_fingerprint(
        output.node_fingerprint, output.instrument_id, canonical
    )
    values = canonical.column("value").to_pylist()
    values[-1] = Decimal("8")
    changed_value = canonical.set_column(1, canonical.schema.field(1), pa.array(values, type=canonical.column(1).type))
    timestamps = canonical.column("ts_event_ns").to_pylist()
    timestamps[-1] += 1
    changed_time = canonical.set_column(0, canonical.schema.field(0), pa.array(timestamps, type=pa.int64()))
    assert fingerprint != only_research_calculation_partition_fingerprint(
        output.node_fingerprint, output.instrument_id, changed_value
    )
    assert fingerprint != only_research_calculation_partition_fingerprint(
        output.node_fingerprint, output.instrument_id, changed_time
    )
    assert fingerprint != only_research_calculation_partition_fingerprint(
        output.node_fingerprint, "OTHER.XNAS", canonical
    )
    assert fingerprint != only_research_calculation_partition_fingerprint("0" * 64, output.instrument_id, canonical)


def test_global_content_identity_canonicalizes_partition_order_and_rejects_duplicates(tmp_path) -> None:
    _, store, graph, execution = _case(tmp_path)
    result = store.commit(execution, graph)
    descriptors = tuple(
        (
            item.node_fingerprint,
            item.instrument_id,
            item.row_count,
            item.semantic_fingerprint,
            item.arrow_schema,
        )
        for item in result.manifest.partitions
    )
    assert only_research_calculation_result_content_fingerprint(
        tuple(reversed(descriptors))
    ) == only_research_calculation_result_content_fingerprint(descriptors)
    with pytest.raises(ValueError, match="duplicate logical partition"):
        only_research_calculation_result_content_fingerprint((descriptors[0], descriptors[0]))


@pytest.mark.parametrize(
    ("data_type", "arrow_type", "values"),
    (
        (OnlyCalculationDataType.INTEGER, pa.uint16(), [1, 2, None, 4]),
        (OnlyCalculationDataType.BOOLEAN, pa.bool_(), [True, False, None, True]),
        (OnlyCalculationDataType.STRING, pa.string(), ["a", "b", None, "d"]),
    ),
)
def test_store_preserves_all_supported_logical_output_types(tmp_path, data_type, arrow_type, values) -> None:
    dataset_store, _, _, base = _case(tmp_path)
    definition = replace(
        resolve_definition(TYPES[0], {"period": 2}),
        outputs=(replace(resolve_definition(TYPES[0], {"period": 2}).outputs[0], data_type=data_type),),
    )
    graph = OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(definition),))
    outputs = tuple(
        OnlyResearchCalculationNodeOutput(
            graph.ordered_nodes[0].fingerprint,
            output.instrument_id,
            pa.table(
                {
                    "ts_event_ns": output.table.column("ts_event_ns"),
                    "value": pa.array(values, type=arrow_type),
                }
            ),
        )
        for output in base.outputs
    )
    calculation = only_research_calculation_fingerprint(base.dataset_snapshot_fingerprint, graph.fingerprint)
    execution = OnlyResearchCalculationExecution(
        calculation,
        base.dataset_snapshot_fingerprint,
        graph.fingerprint,
        outputs,
    )
    store = OnlyParquetResearchCalculationResultStore(
        tmp_path / f"results-{data_type.value}", dataset_store, audit_time=lambda: _AUDIT_TIME
    )
    loaded = store.commit(execution, graph)
    assert loaded.outputs[0].table.column("value").to_pylist() == values


def test_non_nullable_output_with_null_is_rejected_at_durable_admission(tmp_path) -> None:
    dataset_store, _, _, base = _case(tmp_path)
    original = resolve_definition(TYPES[0], {"period": 2})
    definition = replace(original, outputs=(replace(original.outputs[0], nullable=False),))
    graph = OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(definition),))
    outputs = tuple(
        OnlyResearchCalculationNodeOutput(
            graph.ordered_nodes[0].fingerprint,
            output.instrument_id,
            pa.table(
                {
                    "ts_event_ns": output.table.column("ts_event_ns"),
                    "value": pa.array([Decimal("1"), None, Decimal("3"), Decimal("4")], type=pa.decimal128(38, 18)),
                }
            ),
        )
        for output in base.outputs
    )
    calculation = only_research_calculation_fingerprint(base.dataset_snapshot_fingerprint, graph.fingerprint)
    execution = OnlyResearchCalculationExecution(
        calculation, base.dataset_snapshot_fingerprint, graph.fingerprint, outputs
    )
    store = OnlyParquetResearchCalculationResultStore(
        tmp_path / "results-null", dataset_store, audit_time=lambda: _AUDIT_TIME
    )
    with pytest.raises(OnlyResearchCalculationResultStoreError) as raised:
        store.commit(execution, graph)
    assert raised.value.code == "RESULT_INVALID"
    assert "nullability" in raised.value.detail


def test_different_result_for_same_calculation_fails_closed_and_preserves_first(tmp_path) -> None:
    _, store, graph, execution = _case(tmp_path)
    first = store.commit(execution, graph)
    with pytest.raises(OnlyResearchCalculationResultStoreError) as raised:
        store.commit(_changed(execution), graph)
    assert raised.value.code == "DETERMINISTIC_RESULT_CONFLICT"
    assert store.load_verified(execution.calculation_fingerprint) == first


@pytest.mark.parametrize("mutation", ("append", "modify", "truncate", "missing"))
def test_physical_partition_corruption_fails_closed(tmp_path, mutation) -> None:
    _, store, graph, execution = _case(tmp_path)
    committed = store.commit(execution, graph)
    root = _root(tmp_path / "results", execution.calculation_fingerprint)
    path = root / committed.manifest.partitions[0].relative_path
    if mutation == "append":
        path.write_bytes(path.read_bytes() + b"tamper")
    elif mutation == "modify":
        data = bytearray(path.read_bytes())
        data[len(data) // 2] ^= 1
        path.write_bytes(data)
    elif mutation == "truncate":
        path.write_bytes(path.read_bytes()[:20])
    else:
        path.unlink()
    with pytest.raises(OnlyResearchCalculationResultStoreError) as raised:
        store.load_verified(execution.calculation_fingerprint)
    assert raised.value.code == "RESULT_CORRUPT"
    with pytest.raises(OnlyResearchCalculationResultStoreError, match="RESULT_CORRUPT"):
        store.commit(execution, graph)


def test_semantic_tamper_with_recomputed_byte_hash_still_fails(tmp_path) -> None:
    _, store, graph, execution = _case(tmp_path)
    committed = store.commit(execution, graph)
    root = _root(tmp_path / "results", execution.calculation_fingerprint)
    manifest_path = root / "manifest.json"
    payload = json.loads(manifest_path.read_text())
    partition_path = root / committed.manifest.partitions[0].relative_path
    table = pq.read_table(partition_path)
    values = table.column("value").to_pylist()
    values[-1] = Decimal("123")
    pq.write_table(
        table.set_column(1, table.schema.field(1), pa.array(values, type=table.column(1).type)), partition_path
    )
    import hashlib

    payload["partitions"][0]["byte_sha256"] = hashlib.sha256(partition_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(payload))
    with pytest.raises(OnlyResearchCalculationResultStoreError) as raised:
        store.load_verified(execution.calculation_fingerprint)
    assert raised.value.code == "RESULT_CORRUPT"
    assert "semantic fingerprint" in raised.value.detail


@pytest.mark.parametrize(
    "mutation",
    (
        lambda payload: payload.update({"unknown": True}),
        lambda payload: payload.pop("created_at"),
        lambda payload: payload.update({"schema_version": 999}),
        lambda payload: payload.update({"partition_count": "2"}),
        lambda payload: payload.update({"result_content_fingerprint": "bad"}),
        lambda payload: payload.update({"total_row_count": -1}),
        lambda payload: payload["partitions"][0].update({"relative_path": "../escape.parquet"}),
        lambda payload: payload["partitions"][0].update({"relative_path": "/absolute.parquet"}),
        lambda payload: payload["partitions"][0].update({"relative_path": "data\\..\\escape.parquet"}),
        lambda payload: payload["partitions"].append(dict(payload["partitions"][0])),
        lambda payload: payload["partitions"][0].update({"node_fingerprint": "0" * 64}),
        lambda payload: payload["partitions"][0].update({"instrument_id": "OTHER.XNAS"}),
        lambda payload: payload["partitions"][0].update({"row_count": 999}),
        lambda payload: payload.update({"calculation_result_fingerprint": "0" * 64}),
    ),
    ids=(
        "unknown-field",
        "missing-field",
        "schema-version",
        "wrong-type",
        "invalid-sha",
        "negative-count",
        "traversal",
        "absolute-path",
        "windows-traversal",
        "duplicate-partition",
        "wrong-node",
        "wrong-instrument",
        "wrong-row-count",
        "wrong-result-fingerprint",
    ),
)
def test_manifest_is_exact_and_all_identity_tampering_fails_closed(tmp_path, mutation) -> None:
    _, store, graph, execution = _case(tmp_path)
    store.commit(execution, graph)
    path = _root(tmp_path / "results", execution.calculation_fingerprint) / "manifest.json"
    payload = json.loads(path.read_text())
    mutation(payload)
    path.write_text(json.dumps(payload))
    with pytest.raises(OnlyResearchCalculationResultStoreError) as raised:
        store.load_verified(execution.calculation_fingerprint)
    assert raised.value.code == "RESULT_CORRUPT"


@pytest.mark.parametrize(
    "mutation",
    (
        lambda execution, graph: replace(execution, calculation_graph_fingerprint="0" * 64),
        lambda execution, graph: replace(execution, calculation_fingerprint="0" * 64),
        lambda execution, graph: replace(execution, outputs=execution.outputs[:-1]),
        lambda execution, graph: replace(execution, outputs=(*execution.outputs, execution.outputs[0])),
        lambda execution, graph: replace(
            execution,
            outputs=(replace(execution.outputs[0], node_fingerprint="0" * 64), *execution.outputs[1:]),
        ),
        lambda execution, graph: replace(
            execution,
            outputs=(replace(execution.outputs[0], instrument_id="OTHER.XNAS"), *execution.outputs[1:]),
        ),
        lambda execution, graph: replace(
            execution,
            outputs=(
                replace(execution.outputs[0], table=execution.outputs[0].table.drop(["value"])),
                *execution.outputs[1:],
            ),
        ),
        lambda execution, graph: replace(
            execution,
            outputs=(
                replace(
                    execution.outputs[0],
                    table=execution.outputs[0].table.append_column(
                        "unexpected", pa.array([1] * execution.outputs[0].table.num_rows)
                    ),
                ),
                *execution.outputs[1:],
            ),
        ),
        lambda execution, graph: replace(
            execution,
            outputs=(
                replace(
                    execution.outputs[0],
                    table=execution.outputs[0].table.set_column(
                        1, "value", pa.array(range(execution.outputs[0].table.num_rows), type=pa.int64())
                    ),
                ),
                *execution.outputs[1:],
            ),
        ),
        lambda execution, graph: replace(
            execution,
            outputs=(
                replace(
                    execution.outputs[0],
                    table=execution.outputs[0].table.set_column(
                        0,
                        "wrong_timestamp",
                        execution.outputs[0].table.column("ts_event_ns"),
                    ),
                ),
                *execution.outputs[1:],
            ),
        ),
        lambda execution, graph: replace(
            execution,
            outputs=(
                replace(
                    execution.outputs[0],
                    table=execution.outputs[0].table.set_column(
                        0,
                        "ts_event_ns",
                        pa.array(
                            list(reversed(execution.outputs[0].table.column("ts_event_ns").to_pylist())),
                            type=pa.int64(),
                        ),
                    ),
                ),
                *execution.outputs[1:],
            ),
        ),
    ),
    ids=(
        "graph-link",
        "calculation-link",
        "missing-partition",
        "duplicate-partition",
        "unknown-node",
        "unknown-instrument",
        "missing-output",
        "unexpected-output",
        "wrong-output-type",
        "wrong-timestamp-column",
        "noncanonical-timestamps",
    ),
)
def test_durable_admission_rejects_forged_or_incomplete_execution(tmp_path, mutation) -> None:
    _, store, graph, execution = _case(tmp_path)
    with pytest.raises(OnlyResearchCalculationResultStoreError) as raised:
        store.commit(mutation(execution, graph), graph)
    assert raised.value.code == "RESULT_INVALID"
    assert not store.exists(execution.calculation_fingerprint)


def test_unexpected_physical_partition_is_rejected(tmp_path) -> None:
    _, store, graph, execution = _case(tmp_path)
    store.commit(execution, graph)
    root = _root(tmp_path / "results", execution.calculation_fingerprint)
    (root / "data" / "extra.parquet").write_bytes(b"extra")
    with pytest.raises(OnlyResearchCalculationResultStoreError, match="RESULT_CORRUPT"):
        store.load_verified(execution.calculation_fingerprint)


def test_symlink_partition_is_rejected_as_corruption(tmp_path) -> None:
    _, store, graph, execution = _case(tmp_path)
    committed = store.commit(execution, graph)
    root = _root(tmp_path / "results", execution.calculation_fingerprint)
    path = root / committed.manifest.partitions[0].relative_path
    outside = tmp_path / "outside.parquet"
    path.replace(outside)
    try:
        path.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(OnlyResearchCalculationResultStoreError) as raised:
        store.load_verified(execution.calculation_fingerprint)
    assert raised.value.code == "RESULT_CORRUPT"


def test_failure_before_rename_is_invisible_and_stage_is_cleaned(tmp_path, monkeypatch) -> None:
    _, store, graph, execution = _case(tmp_path)
    import onlyalpha.research.calculation.result_store as module

    monkeypatch.setattr(module.os, "rename", lambda source, target: (_ for _ in ()).throw(OSError("injected")))
    with pytest.raises(OnlyResearchCalculationResultStoreError) as raised:
        store.commit(execution, graph)
    assert raised.value.code == "RESULT_COMMIT_FAILED"
    assert not store.exists(execution.calculation_fingerprint)
    parent = tmp_path / "results" / "sha256" / execution.calculation_fingerprint[:2]
    assert not [item for item in parent.iterdir() if item.name.startswith(".stage-")]


def test_partition_write_failure_is_invisible_and_stage_is_cleaned(tmp_path, monkeypatch) -> None:
    _, store, graph, execution = _case(tmp_path)
    import onlyalpha.research.calculation.result_store as module

    monkeypatch.setattr(module.pq, "write_table", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("injected")))
    with pytest.raises(OnlyResearchCalculationResultStoreError) as raised:
        store.commit(execution, graph)
    assert raised.value.code == "RESULT_COMMIT_FAILED"
    assert not store.exists(execution.calculation_fingerprint)
    parent = tmp_path / "results" / "sha256" / execution.calculation_fingerprint[:2]
    assert not [item for item in parent.iterdir() if item.name.startswith(".stage-")]


def test_staging_verification_failure_is_commit_failure_and_invisible(tmp_path, monkeypatch) -> None:
    _, store, graph, execution = _case(tmp_path)
    import onlyalpha.research.calculation.result_store as module

    original = module.OnlyParquetResearchCalculationResultStore._read_verified

    def fail_stage(self, root, expected):
        if root.name.startswith(".stage-"):
            raise OnlyResearchCalculationResultStoreError("RESULT_CORRUPT", "injected stage failure")
        return original(self, root, expected)

    monkeypatch.setattr(module.OnlyParquetResearchCalculationResultStore, "_read_verified", fail_stage)
    with pytest.raises(OnlyResearchCalculationResultStoreError) as raised:
        store.commit(execution, graph)
    assert raised.value.code == "RESULT_COMMIT_FAILED"
    assert not store.exists(execution.calculation_fingerprint)


def test_race_like_existing_same_result_is_idempotent(tmp_path, monkeypatch) -> None:
    _, store, graph, execution = _case(tmp_path)
    import onlyalpha.research.calculation.result_store as module

    real_rename = os.rename

    def publish_then_report_race(source, target):
        real_rename(source, target)
        raise OSError("target won by peer")

    monkeypatch.setattr(module.os, "rename", publish_then_report_race)
    result = store.commit(execution, graph)
    assert result.manifest.calculation_fingerprint == execution.calculation_fingerprint
    assert store.load_verified(execution.calculation_fingerprint) == result


def test_concurrent_same_result_has_one_authority(tmp_path) -> None:
    _, store, graph, execution = _case(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _: store.commit(execution, graph), range(2)))
    assert results[0] == results[1]
    parent = tmp_path / "results" / "sha256" / execution.calculation_fingerprint[:2]
    assert [item.name for item in parent.iterdir() if not item.name.startswith(".stage-")] == [
        execution.calculation_fingerprint
    ]


def test_empty_graph_has_one_canonical_empty_result(tmp_path) -> None:
    dataset_store = OnlyParquetResearchDatasetSnapshotStore(tmp_path / "datasets")
    candidate, partitions = snapshot()
    dataset_store.commit(candidate, partitions)
    graph = OnlyCalculationGraphDefinition(())
    execution = OnlyResearchCalculationExecutor(
        dataset_store, OnlyResearchCalculationBackendResolver(_registry())
    ).execute(candidate.snapshot_fingerprint, graph)
    store = OnlyParquetResearchCalculationResultStore(
        tmp_path / "results", dataset_store, audit_time=lambda: _AUDIT_TIME
    )
    result = store.commit(execution, graph)
    assert result.outputs == ()
    assert result.manifest.partition_count == result.manifest.total_row_count == 0
    assert store.load_verified(execution.calculation_fingerprint) == result


def test_fresh_process_verified_reload_preserves_all_identities_and_values(tmp_path) -> None:
    _, store, graph, execution = _case(tmp_path)
    committed = store.commit(execution, graph)
    code = (
        "import json,sys; from pathlib import Path; "
        "from onlyalpha.research import OnlyParquetResearchDatasetSnapshotStore; "
        "from onlyalpha.research.calculation import OnlyParquetResearchCalculationResultStore; "
        "d=OnlyParquetResearchDatasetSnapshotStore(Path(sys.argv[1])); "
        "r=OnlyParquetResearchCalculationResultStore(Path(sys.argv[2]),d).load_verified(sys.argv[3]); "
        "print(json.dumps({'calculation':r.manifest.calculation_fingerprint,'content':r.manifest.result_content_fingerprint,"
        "'result':r.manifest.calculation_result_fingerprint,'outputs':[x.table.to_pydict() for x in r.outputs]},"
        "default=str,sort_keys=True))"
    )
    value = json.loads(
        subprocess.check_output(
            [
                sys.executable,
                "-c",
                code,
                str(tmp_path / "datasets"),
                str(tmp_path / "results"),
                execution.calculation_fingerprint,
            ],
            text=True,
        )
    )
    assert value["calculation"] == execution.calculation_fingerprint
    assert value["content"] == committed.manifest.result_content_fingerprint
    assert value["result"] == committed.manifest.calculation_result_fingerprint
    assert value["outputs"] == json.loads(
        json.dumps([item.table.to_pydict() for item in committed.outputs], default=str)
    )


def test_not_found_and_invalid_key_have_stable_errors(tmp_path) -> None:
    _, store, _, execution = _case(tmp_path)
    with pytest.raises(OnlyResearchCalculationResultStoreError) as missing:
        store.load_verified(execution.calculation_fingerprint)
    assert missing.value.code == "RESULT_NOT_FOUND"
    with pytest.raises(OnlyResearchCalculationResultStoreError) as invalid:
        store.load_verified("not-a-sha")
    assert invalid.value.code == "RESULT_NOT_FOUND"


@pytest.mark.parametrize("audit_time", (None, lambda: datetime(2026, 8, 14)))
def test_commit_requires_explicit_utc_audit_time_authority(tmp_path, audit_time) -> None:
    dataset_store, _, graph, execution = _case(tmp_path)
    store = OnlyParquetResearchCalculationResultStore(tmp_path / "audit-results", dataset_store, audit_time=audit_time)
    with pytest.raises(OnlyResearchCalculationResultStoreError) as raised:
        store.commit(execution, graph)
    assert raised.value.code == "RESULT_INVALID"
    assert not store.exists(execution.calculation_fingerprint)
