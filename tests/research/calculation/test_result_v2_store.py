from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import Barrier, Event

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from onlyalpha.calculation import OnlyCalculationGraphDefinition, OnlyCalculationNodeDefinition
from onlyalpha.research.calculation.errors import OnlyResearchCalculationResultStoreError
from onlyalpha.research.calculation.identity import only_research_calculation_fingerprint
from onlyalpha.research.calculation.readiness import OnlyResearchOutputReadiness
from onlyalpha.research.calculation.result_store import OnlyParquetResearchCalculationResultStore
from onlyalpha.research.calculation.result_v2 import OnlyResearchCalculationResultManifestV2
from onlyalpha.research.calculation.result_v2_identity import (
    _descriptor,
    only_research_calculation_result_content_fingerprint_v2,
    only_research_calculation_result_fingerprint_v2,
    only_research_calculation_value_projection_fingerprint,
)
from onlyalpha.research.calculation.result_v2_store import OnlyParquetResearchCalculationResultStoreV2
from tests.research.calculation.test_execution_readiness_v2 import (
    PUBLICATION,
    SMA,
    _AtomicBackend,
    _graph,
    _registry,
    _setup,
)

AUDIT = datetime(2026, 10, 3, tzinfo=UTC)


def _case(tmp_path, registry=None):
    executor, spy, snapshot = _setup(tmp_path / "datasets", registry)
    graph = _graph()
    sealed = executor._execute_verified_v2(snapshot, graph, PUBLICATION)
    store = OnlyParquetResearchCalculationResultStoreV2(tmp_path / "results", spy.store, audit_time=lambda: AUDIT)
    return executor, store, graph, sealed


def _root(tmp_path, sealed):
    fingerprint = sealed.execution.calculation_fingerprint
    return tmp_path / "results" / "v2" / "sha256" / fingerprint[:2] / fingerprint


def test_v2_round_trip_zero_parity_and_immutable_reuse(tmp_path):
    executor, store, graph, sealed = _case(tmp_path)
    before = executor._store.store.load_verified_table(sealed.execution.dataset_snapshot_fingerprint).table
    result = store.commit(sealed, graph)
    assert store.exists(sealed.execution.calculation_fingerprint)
    assert store.load_verified(sealed.execution.calculation_fingerprint) == result
    assert store.commit(sealed, graph) == result
    assert store.verify(sealed.execution.calculation_fingerprint).valid
    assert result.outputs[0].table["value"][0].as_py() == Decimal("0.000000000000")
    assert result.readiness[0].table["readiness"].to_pylist() == ["PARTIAL", "PARTIAL", "READY", "READY"]
    legacy_store = OnlyParquetResearchCalculationResultStore(
        tmp_path / "results", executor._store.store, audit_time=lambda: AUDIT
    )
    legacy = legacy_store.commit(executor.execute(sealed.execution.dataset_snapshot_fingerprint, graph), graph)
    assert all(a.table.equals(b.table) for a, b in zip(result.outputs, legacy.outputs, strict=True))
    assert result.manifest.calculation_result_fingerprint != legacy.manifest.calculation_result_fingerprint
    assert (tmp_path / "results" / "sha256" / sealed.execution.calculation_fingerprint[:2]).is_dir()
    assert executor._store.store.load_verified_table(sealed.execution.dataset_snapshot_fingerprint).table.equals(before)
    assert OnlyResearchCalculationResultManifestV2.from_dict(result.manifest.to_dict()) == result.manifest


def test_v2_identity_excludes_encoding_and_audit(tmp_path):
    executor, store, graph, sealed = _case(tmp_path)
    first = store.commit(sealed, graph)
    second = OnlyParquetResearchCalculationResultStoreV2(
        tmp_path / "other",
        executor._store.store,
        compression="snappy",
        row_group_size=1,
        audit_time=lambda: datetime(2025, 1, 1, tzinfo=UTC),
    ).commit(sealed, graph)
    for field in ("value_projection_fingerprint", "result_content_fingerprint", "calculation_result_fingerprint"):
        assert getattr(first.manifest, field) == getattr(second.manifest, field)
    assert first.manifest.created_at != second.manifest.created_at
    assert first.manifest.value_partitions[0].byte_sha256 != second.manifest.value_partitions[0].byte_sha256


def test_v2_readiness_changes_identity_and_conflicts_without_replacing(tmp_path):
    executor, store, graph, sealed = _case(tmp_path)
    first = store.commit(sealed, graph)

    def same_values(outputs, readiness, calls):
        values = sealed.execution.outputs[calls - 1].table["value"]
        outputs["value"] = values

    other_executor, _, _ = _setup(tmp_path / "datasets", _registry(_AtomicBackend(same_values)))
    other = other_executor._execute_verified_v2(sealed.execution.dataset_snapshot_fingerprint, graph, PUBLICATION)
    different = OnlyParquetResearchCalculationResultStoreV2(
        tmp_path / "different", executor._store.store, audit_time=lambda: AUDIT
    ).commit(other, graph)
    assert different.manifest.value_projection_fingerprint == first.manifest.value_projection_fingerprint
    assert different.manifest.result_content_fingerprint != first.manifest.result_content_fingerprint
    assert different.manifest.calculation_result_fingerprint != first.manifest.calculation_result_fingerprint
    with pytest.raises(OnlyResearchCalculationResultStoreError, match="DETERMINISTIC_RESULT_CONFLICT"):
        store.commit(other, graph)
    assert store.load_verified(sealed.execution.calculation_fingerprint) == first


def _repair_envelope(root, payload):
    families = []
    for name in ("value_partitions", "readiness_partitions"):
        descriptors = []
        for partition in payload[name]:
            path = root / partition["relative_path"]
            table = pq.read_table(path)
            descriptor = _descriptor(
                partition["node_fingerprint"],
                partition["instrument_id"],
                table,
                readiness=name == "readiness_partitions",
            )
            partition.update(
                row_count=descriptor[2],
                semantic_fingerprint=descriptor[3],
                arrow_schema=list(descriptor[4]),
                byte_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            descriptors.append(descriptor)
        families.append(tuple(descriptors))
    payload["value_projection_fingerprint"] = only_research_calculation_value_projection_fingerprint(families[0])
    payload["result_content_fingerprint"] = only_research_calculation_result_content_fingerprint_v2(*families)
    payload["calculation_result_fingerprint"] = only_research_calculation_result_fingerprint_v2(
        payload["calculation_fingerprint"], payload["result_content_fingerprint"]
    )
    (root / "manifest.json").write_text(json.dumps(payload))


@pytest.mark.parametrize("candidate", ("public", "copied", "substituted", "wrong-family", "missing"))
def test_v2_store_requires_actual_issued_seal(tmp_path, candidate):
    executor, store, graph, sealed = _case(tmp_path)
    values = {
        "public": sealed.execution,
        "copied": replace(sealed),
        "substituted": replace(sealed, execution=replace(sealed.execution, readiness=())),
        "wrong-family": executor._execute_verified(sealed.execution.dataset_snapshot_fingerprint, graph),
        "missing": None,
    }
    with pytest.raises(Exception, match="RESEARCH_EXECUTION_PUBLICATION_UNAUTHORIZED"):
        store.commit(values[candidate], graph)
    assert not store.exists(sealed.execution.calculation_fingerprint)


@pytest.mark.parametrize("kind", ("file", "dangling-symlink", "empty-directory"))
def test_v2_malformed_existing_root_is_not_absent_or_replaced(tmp_path, kind):
    _, store, graph, sealed = _case(tmp_path)
    root = _root(tmp_path, sealed)
    root.parent.mkdir(parents=True)
    if kind == "file":
        root.write_bytes(b"do not replace")
    elif kind == "dangling-symlink":
        root.symlink_to(tmp_path / "missing")
    else:
        root.mkdir()
    for action in (
        lambda: store.exists(sealed.execution.calculation_fingerprint),
        lambda: store.load_verified(sealed.execution.calculation_fingerprint),
        lambda: store.commit(sealed, graph),
    ):
        with pytest.raises(OnlyResearchCalculationResultStoreError, match="RESULT_CORRUPT"):
            action()
    assert root.is_symlink() if kind == "dangling-symlink" else root.exists()
    if kind == "file":
        assert root.read_bytes() == b"do not replace"


@pytest.mark.parametrize("section", ("value_partitions", "readiness_partitions"))
@pytest.mark.parametrize(
    "mutation", ("byte", "missing", "symlink", "extra", "value", "axis", "duplicate-axis", "output", "type", "reason")
)
def test_v2_physical_and_repaired_envelope_logical_corruption(tmp_path, section, mutation):
    _, store, graph, sealed = _case(tmp_path)
    result = store.commit(sealed, graph)
    root = _root(tmp_path, sealed)
    payload = result.manifest.to_dict()
    partition = payload[section][0]
    path = root / partition["relative_path"]
    if mutation == "byte":
        path.write_bytes(path.read_bytes() + b"bad")
    elif mutation == "missing":
        path.unlink()
    elif mutation == "symlink":
        outside = tmp_path / "outside"
        path.rename(outside)
        path.symlink_to(outside)
    elif mutation == "extra":
        (path.parent / "extra").write_bytes(b"bad")
    else:
        table = pq.read_table(path)
        column = "value" if section == "value_partitions" else "readiness"
        if mutation in ("axis", "duplicate-axis"):
            axis = table["ts_event_ns"].to_pylist()
            axis[-1] = axis[0] if mutation == "duplicate-axis" else axis[-1] + 1
            table = table.set_column(0, table.schema.field(0), pa.array(axis, type=pa.int64()))
        elif mutation == "output":
            table = table.rename_columns(["bad", *table.column_names[1:]])
        elif mutation == "type":
            index = table.column_names.index(column)
            table = table.set_column(index, pa.field(column, pa.int64()), pa.array([1] * table.num_rows))
        else:
            index = table.column_names.index(column)
            values = table[column].to_pylist()
            values[0] = Decimal("99") if section == "value_partitions" else ("BAD" if mutation == "reason" else "READY")
            table = table.set_column(index, table.schema.field(index), pa.array(values, type=table[column].type))
        pq.write_table(table, path)
        partition["byte_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        (root / "manifest.json").write_text(json.dumps(payload))
    for action in (
        lambda: store.load_verified(sealed.execution.calculation_fingerprint),
        lambda: store.commit(sealed, graph),
    ):
        with pytest.raises(OnlyResearchCalculationResultStoreError, match="RESULT_CORRUPT"):
            action()


@pytest.mark.parametrize(
    "mutation",
    (
        "context",
        "owner",
        "source",
        "graph",
        "node",
        "instrument",
        "duplicate",
        "missing-readiness",
        "family",
        "complete-different",
        "bool",
        "float",
        "unknown",
        "schema-type",
    ),
)
def test_v2_manifest_structural_mutations_fail_closed(tmp_path, mutation):
    _, store, graph, sealed = _case(tmp_path)
    result = store.commit(sealed, graph)
    payload = result.manifest.to_dict()
    if mutation == "context":
        payload = {}
    elif mutation in ("owner", "source", "graph"):
        payload.pop(
            {
                "owner": "calculation_fingerprint",
                "source": "dataset_snapshot_fingerprint",
                "graph": "calculation_graph",
            }[mutation]
        )
    elif mutation in ("node", "instrument"):
        payload["readiness_partitions"][0]["node_fingerprint" if mutation == "node" else "instrument_id"] = (
            "0" * 64 if mutation == "node" else "C.XNAS"
        )
    elif mutation == "duplicate":
        payload["readiness_partitions"].append(payload["readiness_partitions"][0])
    elif mutation == "missing-readiness":
        payload["readiness_partitions"] = []
    elif mutation in ("family", "bool", "float"):
        payload["schema_version"] = {"family": 1, "bool": True, "float": 2.0}[mutation]
    elif mutation == "complete-different":
        payload["calculation_graph"] = _graph(1).to_dict()
        payload["calculation_graph_fingerprint"] = _graph(1).fingerprint
    elif mutation == "unknown":
        payload["unknown"] = 1
    else:
        payload["value_partitions"][0]["arrow_schema"][1]["data_type"]["precision"] = True
    (_root(tmp_path, sealed) / "manifest.json").write_text(json.dumps(payload))
    with pytest.raises(OnlyResearchCalculationResultStoreError, match="RESULT_CORRUPT"):
        store.load_verified(sealed.execution.calculation_fingerprint)


def test_v2_restart_verified_load(tmp_path):
    _, store, graph, sealed = _case(tmp_path)
    result = store.commit(sealed, graph)
    code = """
import json, sys
from pathlib import Path
from onlyalpha.research.dataset import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.calculation.result_v2_store import OnlyParquetResearchCalculationResultStoreV2
s = OnlyParquetResearchCalculationResultStoreV2(Path(sys.argv[2]), OnlyParquetResearchDatasetSnapshotStore(Path(sys.argv[1])))
r = s.load_verified(sys.argv[3])
print(json.dumps({'manifest': r.manifest.to_dict(), 'values': [x.table.to_pydict() for x in r.outputs], 'readiness': [x.table.to_pydict() for x in r.readiness]}, default=str))
"""
    loaded = json.loads(
        subprocess.check_output(
            [
                sys.executable,
                "-c",
                code,
                str(tmp_path / "datasets"),
                str(tmp_path / "results"),
                sealed.execution.calculation_fingerprint,
            ],
            text=True,
        )
    )
    assert loaded == json.loads(
        json.dumps(
            {
                "manifest": result.manifest.to_dict(),
                "values": [x.table.to_pydict() for x in result.outputs],
                "readiness": [x.table.to_pydict() for x in result.readiness],
            },
            default=str,
        )
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "axis",
        "duplicate-axis",
        "missing-output",
        "extra-output",
        "order",
        "reason",
        "pair",
        "null",
        "node",
        "instrument",
        "family",
        "row-count",
        "nullable",
    ),
)
def test_v2_rejects_structurally_invalid_proof_even_with_all_hashes_repaired(tmp_path, mutation):
    _, store, graph, sealed = _case(tmp_path)
    result = store.commit(sealed, graph)
    payload = result.manifest.to_dict()
    root = _root(tmp_path, sealed)
    partition = payload["readiness_partitions"][0]
    path = root / partition["relative_path"]
    table = pq.read_table(path)
    if mutation in ("node", "instrument"):
        field = "node_fingerprint" if mutation == "node" else "instrument_id"
        for name in ("value_partitions", "readiness_partitions"):
            payload[name][0][field] = "0" * 64 if mutation == "node" else "C.XNAS"
    elif mutation == "family":
        partition["relative_path"] = payload["value_partitions"][0]["relative_path"]
    elif mutation == "row-count":
        table = table.slice(1)
    elif mutation == "nullable":
        table = table.cast(pa.schema([pa.field(field.name, field.type, True) for field in table.schema]))
    elif mutation == "order":
        table = table.take(pa.array([3, 2, 1, 0]))
    else:
        field = (
            "ts_event_ns"
            if mutation in ("axis", "duplicate-axis")
            else "output_name"
            if mutation in ("missing-output", "extra-output")
            else "reason"
            if mutation == "reason"
            else "readiness"
        )
        values = table[field].to_pylist()
        values[0] = {
            "axis": 0,
            "duplicate-axis": values[-1],
            "missing-output": "absent",
            "extra-output": "extra",
            "reason": "NONE",
            "pair": "READY",
            "null": None,
        }[mutation]
        index = table.column_names.index(field)
        arrow_field = table.schema.field(index)
        if mutation == "null":
            arrow_field = pa.field(field, arrow_field.type, nullable=True)
        table = table.set_column(index, arrow_field, pa.array(values, type=table[field].type))
    if mutation not in ("node", "instrument", "family"):
        pq.write_table(table, path)
    _repair_envelope(root, payload)
    for action in (
        lambda: store.load_verified(sealed.execution.calculation_fingerprint),
        lambda: store.exists(sealed.execution.calculation_fingerprint),
        lambda: store.commit(sealed, graph),
    ):
        with pytest.raises(OnlyResearchCalculationResultStoreError, match="RESULT_CORRUPT"):
            action()


@pytest.mark.parametrize("point", ("write", "stage-verify", "rename"))
def test_v2_failed_publication_is_invisible_and_stage_is_cleaned(tmp_path, monkeypatch, point):
    import onlyalpha.research.calculation.result_v2_store as module

    _, store, graph, sealed = _case(tmp_path)

    def fail(*args, **kwargs):
        raise OSError("injected")

    if point == "write":
        monkeypatch.setattr(module.pq, "write_table", fail)
    elif point == "rename":
        monkeypatch.setattr(module, "_rename_exclusive", fail)
    else:
        original = store._read_verified

        def read(root, fingerprint):
            if root.name.startswith(".stage-"):
                raise OnlyResearchCalculationResultStoreError("RESULT_CORRUPT", "injected")
            return original(root, fingerprint)

        monkeypatch.setattr(store, "_read_verified", read)
    with pytest.raises(OnlyResearchCalculationResultStoreError, match="RESULT_COMMIT_FAILED"):
        store.commit(sealed, graph)
    assert not store.exists(sealed.execution.calculation_fingerprint)
    assert list(_root(tmp_path, sealed).parent.iterdir()) == []


@pytest.mark.parametrize("kind", ("same", "conflict", "empty-directory", "file", "dangling-symlink", "corrupt"))
def test_v2_atomic_race_loser_verifies_and_never_replaces_winner(tmp_path, monkeypatch, kind):
    import onlyalpha.research.calculation.result_v2_store as module

    _, store, graph, sealed = _case(tmp_path)
    original = module._rename_exclusive
    root = _root(tmp_path, sealed)

    def race(stage, target):
        if kind in ("same", "conflict", "corrupt"):
            if kind == "conflict":
                payload = json.loads((stage / "manifest.json").read_text())
                path = stage / payload["readiness_partitions"][0]["relative_path"]
                table = pq.read_table(path)
                table = table.set_column(2, table.schema.field(2), pa.array(["READY"] * 4))
                table = table.set_column(3, table.schema.field(3), pa.array(["NONE"] * 4))
                pq.write_table(table, path)
                _repair_envelope(stage, payload)
            original(stage, target)
            if kind == "corrupt":
                (target / "manifest.json").write_text("{}")
            raise FileExistsError("peer won")
        if kind == "empty-directory":
            target.mkdir()
        elif kind == "file":
            target.write_bytes(b"winner")
        else:
            target.symlink_to(tmp_path / "missing")
        original(stage, target)

    monkeypatch.setattr(module, "_rename_exclusive", race)
    if kind == "same":
        assert store.commit(sealed, graph) == store.load_verified(sealed.execution.calculation_fingerprint)
    else:
        with pytest.raises(
            OnlyResearchCalculationResultStoreError,
            match="DETERMINISTIC_RESULT_CONFLICT" if kind == "conflict" else "RESULT_CORRUPT",
        ):
            store.commit(sealed, graph)
    assert not any(item.name.startswith(".stage-") for item in root.parent.iterdir())
    if kind == "empty-directory":
        assert list(root.iterdir()) == []
    elif kind == "file":
        assert root.read_bytes() == b"winner"
    elif kind == "dangling-symlink":
        assert root.is_symlink()


def test_v2_concurrent_publication_has_one_verified_authority(tmp_path, monkeypatch):
    import onlyalpha.research.calculation.result_v2_store as module

    _, store, graph, sealed = _case(tmp_path)
    barrier = Barrier(2)
    rename = module._rename_exclusive

    def publish(stage, target):
        barrier.wait()
        rename(stage, target)

    monkeypatch.setattr(module, "_rename_exclusive", publish)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _: store.commit(sealed, graph), range(2)))
    assert results[0] == results[1]
    assert list(_root(tmp_path, sealed).parent.iterdir()) == [_root(tmp_path, sealed)]


@pytest.mark.parametrize(
    "public_import",
    (
        "from onlyalpha.research.job.plan import OnlyResearchJobPlan",
        "from onlyalpha.research import OnlyResearchJobPlan",
    ),
)
def test_v2_v1_plan_import_does_not_require_v2_implementations(public_import):
    code = """
import importlib.abc, sys
class RejectV2(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('onlyalpha.research.calculation.result_v2') or fullname.startswith('onlyalpha.research.calculation.execution_evidence_v2'):
            raise AssertionError(fullname)
sys.meta_path.insert(0, RejectV2())
from onlyalpha.research.job.plan import OnlyResearchJobPlan
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition
plan = OnlyResearchJobPlan('0' * 64, OnlyCalculationGraphDefinition(()))
assert plan.schema_version == 1
assert not any('result_v2' in name for name in sys.modules)
"""
    code = code.replace("from onlyalpha.research.job.plan import OnlyResearchJobPlan", public_import)
    subprocess.run([sys.executable, "-c", code], check=True)


@pytest.mark.parametrize("point", ("before-commit", "after-commit"))
def test_v2_upstream_corruption_never_becomes_missing_or_valid(tmp_path, point):
    _, store, graph, sealed = _case(tmp_path)
    if point == "after-commit":
        store.commit(sealed, graph)
    fingerprint = sealed.execution.dataset_snapshot_fingerprint
    root = tmp_path / "datasets" / "sha256" / fingerprint[:2] / fingerprint
    (root / "manifest.json").write_text("{}")
    with pytest.raises(OnlyResearchCalculationResultStoreError, match="RESULT_INVALID"):
        store.commit(sealed, graph)
    if point == "after-commit":
        with pytest.raises(OnlyResearchCalculationResultStoreError, match="RESULT_CORRUPT"):
            store.load_verified(sealed.execution.calculation_fingerprint)


@pytest.mark.parametrize("mutation", (True, 2.0, "2", 99))
def test_v2_typed_manifest_rejects_coerced_versions(tmp_path, mutation):
    _, store, graph, sealed = _case(tmp_path)
    manifest = store.commit(sealed, graph).manifest
    with pytest.raises(ValueError):
        replace(manifest, schema_version=mutation)


def test_v2_commit_rejects_complete_different_graph_before_publication(tmp_path):
    _, store, _, sealed = _case(tmp_path)
    with pytest.raises(OnlyResearchCalculationResultStoreError, match="RESULT_INVALID"):
        store.commit(sealed, _graph(1))
    assert not store.exists(sealed.execution.calculation_fingerprint)


def test_v2_multi_output_membership_and_null_state_space(tmp_path):
    def mutate(outputs, readiness, calls):
        for name in outputs:
            outputs[name] = pa.array([None] * 4, type=outputs[name].type)
            readiness[name] = OnlyResearchOutputReadiness(
                pa.array(["PARTIAL", "READY", "UNAVAILABLE", "UNAVAILABLE"]),
                pa.array(["WARMUP_INCOMPLETE", "VALUE_UNDEFINED", "INPUT_UNAVAILABLE", "DEPENDENCY_UNAVAILABLE"]),
            )

    type_definition = replace(SMA, outputs=(replace(SMA.outputs[0], name="a"), replace(SMA.outputs[0], name="z")))
    executor, spy, fingerprint = _setup(
        tmp_path / "datasets", _registry(_AtomicBackend(mutate), type_definition=type_definition)
    )
    graph = _graph(type_definition=type_definition)
    sealed = executor._execute_verified_v2(fingerprint, graph, PUBLICATION)
    store = OnlyParquetResearchCalculationResultStoreV2(tmp_path / "results", spy.store, audit_time=lambda: AUDIT)
    result = store.commit(sealed, graph)
    assert result.outputs[0].table.column_names == ["ts_event_ns", "a", "z"]
    assert result.readiness[0].table["output_name"].to_pylist() == ["a"] * 4 + ["z"] * 4
    assert result.outputs[0].table["a"].to_pylist() == [None] * 4
    assert store.verify(sealed.execution.calculation_fingerprint).readiness_row_count == 16


def test_v2_self_consistent_graph_with_incompatible_source_fails_upstream_proof(tmp_path):
    _, store, graph, sealed = _case(tmp_path)
    result = store.commit(sealed, graph)
    definition = graph.nodes[0].definition
    reference = replace(definition.input_bindings["value"], source="bar.trade_count")
    changed = OnlyCalculationGraphDefinition(
        (OnlyCalculationNodeDefinition(replace(definition, input_bindings={"value": reference})),)
    )
    payload = result.manifest.to_dict()
    payload["calculation_graph"] = changed.to_dict()
    payload["calculation_graph_fingerprint"] = changed.fingerprint
    fingerprint = only_research_calculation_fingerprint(
        sealed.execution.dataset_snapshot_fingerprint, changed.fingerprint
    )
    payload["calculation_fingerprint"] = fingerprint
    for name in ("value_partitions", "readiness_partitions"):
        for partition in payload[name]:
            partition["node_fingerprint"] = changed.nodes[0].fingerprint
    root = _root(tmp_path, sealed)
    _repair_envelope(root, payload)
    target = store._target(fingerprint)
    target.parent.mkdir(parents=True, exist_ok=True)
    root.rename(target)
    with pytest.raises(OnlyResearchCalculationResultStoreError, match="RESULT_CORRUPT") as raised:
        store.load_verified(fingerprint)
    assert "RESEARCH_INPUT_INCOMPATIBLE" in raised.value.detail


@pytest.mark.parametrize("family", ("values", "readiness", "manifest.json", "v2", "sha256"))
def test_v2_symlinked_authority_entries_are_not_followed(tmp_path, family):
    _, store, graph, sealed = _case(tmp_path)
    store.commit(sealed, graph)
    root = _root(tmp_path, sealed)
    path = (
        root / family
        if family in ("values", "readiness", "manifest.json")
        else tmp_path / "results" / "v2"
        if family == "v2"
        else tmp_path / "results" / "v2" / "sha256"
    )
    outside = tmp_path / "outside"
    path.rename(outside)
    path.symlink_to(outside)
    with pytest.raises(OnlyResearchCalculationResultStoreError, match="RESULT_CORRUPT"):
        store.exists(sealed.execution.calculation_fingerprint)


def test_v2_duplicate_json_fields_fail_closed(tmp_path):
    _, store, graph, sealed = _case(tmp_path)
    store.commit(sealed, graph)
    path = _root(tmp_path, sealed) / "manifest.json"
    text = path.read_text()
    path.write_text('{"schema_version":2,' + text[1:])
    with pytest.raises(OnlyResearchCalculationResultStoreError, match="RESULT_CORRUPT"):
        store.load_verified(sealed.execution.calculation_fingerprint)


def test_v2_ready_zero_is_preserved_from_first_point(tmp_path):
    executor, store, _, sealed = _case(tmp_path)
    graph = _graph(1)
    verified = executor._execute_verified_v2(sealed.execution.dataset_snapshot_fingerprint, graph, PUBLICATION)
    result = store.commit(verified, graph)
    assert result.outputs[0].table["value"][0].as_py() == Decimal("0.000000000000")
    assert result.readiness[0].table["readiness"].to_pylist() == ["READY"] * 4
    assert result.readiness[0].table["reason"].to_pylist() == ["NONE"] * 4


@pytest.mark.parametrize("mutation", ("axis", "duplicate-axis", "missing-output", "type", "row-count", "nullable"))
def test_v2_value_contract_rejects_fully_rehashed_invalid_partitions(tmp_path, mutation):
    _, store, graph, sealed = _case(tmp_path)
    result = store.commit(sealed, graph)
    root = _root(tmp_path, sealed)
    payload = result.manifest.to_dict()
    path = root / payload["value_partitions"][0]["relative_path"]
    table = pq.read_table(path)
    if mutation in ("axis", "duplicate-axis"):
        axis = table["ts_event_ns"].to_pylist()
        axis[-1] = axis[0] if mutation == "duplicate-axis" else axis[-1] + 1
        table = table.set_column(0, table.schema.field(0), pa.array(axis, type=pa.int64()))
    elif mutation == "missing-output":
        table = table.rename_columns(["ts_event_ns", "other"])
    elif mutation == "type":
        table = table.set_column(1, "value", pa.array([1, 2, 3, 4], type=pa.int64()))
    elif mutation == "row-count":
        table = table.slice(1)
    else:
        table = table.cast(pa.schema([pa.field("ts_event_ns", pa.int64(), True), table.schema.field(1)]))
    pq.write_table(table, path)
    _repair_envelope(root, payload)
    with pytest.raises(OnlyResearchCalculationResultStoreError, match="RESULT_CORRUPT"):
        store.load_verified(sealed.execution.calculation_fingerprint)


@pytest.mark.parametrize(
    "field",
    (
        "schema_version",
        "readiness_contract_version",
        "calculation_fingerprint",
        "dataset_snapshot_fingerprint",
        "calculation_graph_fingerprint",
        "calculation_graph",
        "value_projection_fingerprint",
        "result_content_fingerprint",
        "calculation_result_fingerprint",
        "value_partitions",
        "readiness_partitions",
        "created_at",
    ),
)
def test_v2_manifest_every_field_is_mandatory(tmp_path, field):
    _, store, graph, sealed = _case(tmp_path)
    payload = store.commit(sealed, graph).manifest.to_dict()
    del payload[field]
    with pytest.raises(ValueError, match="fields are invalid"):
        OnlyResearchCalculationResultManifestV2.from_dict(payload)


def test_v2_visible_race_loser_establishes_durability_before_acknowledging(tmp_path, monkeypatch):
    import onlyalpha.research.calculation.result_v2_store as module

    _, store, graph, sealed = _case(tmp_path)
    renamed, release = Event(), Event()
    original_rename, original_sync = module._rename_exclusive, module._sync_directory
    synced = []

    def rename(stage, target):
        original_rename(stage, target)
        renamed.set()
        assert release.wait(10), "test failed to release publisher"

    def sync(path, **kwargs):
        original_sync(path, **kwargs)
        synced.append(path)

    monkeypatch.setattr(module, "_rename_exclusive", rename)
    monkeypatch.setattr(module, "_sync_directory", sync)
    with ThreadPoolExecutor(max_workers=1) as pool:
        winner = pool.submit(store.commit, sealed, graph)
        try:
            assert renamed.wait(10), "publisher did not reach rename barrier"
            synced.clear()
            loser = store.commit(sealed, graph)
            root = _root(tmp_path, sealed)
            expected = [root.parent, root.parent.parent, root.parent.parent.parent, tmp_path / "results", tmp_path]
            assert synced[-len(expected) :] == expected
        finally:
            release.set()
        assert winner.result() == loser


@pytest.mark.parametrize("unknown", (False, True))
def test_v2_sync_failure_never_acknowledges_and_reentry_converges(tmp_path, monkeypatch, unknown):
    import onlyalpha.research.calculation.result_v2_store as module

    _, store, graph, sealed = _case(tmp_path)
    rename, sync = module._rename_exclusive, module._sync_directory
    root = _root(tmp_path, sealed)

    def publish(stage, target):
        rename(stage, target)
        if unknown:
            raise OSError("rename succeeded but acknowledgment was lost")

    def fail(path, **kwargs):
        if path == root.parent:
            raise OSError("namespace sync failed")
        sync(path, **kwargs)

    monkeypatch.setattr(module, "_rename_exclusive", publish)
    monkeypatch.setattr(module, "_sync_directory", fail)
    with pytest.raises(OnlyResearchCalculationResultStoreError, match="RESULT_COMMIT_FAILED"):
        store.commit(sealed, graph)
    before = {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    with pytest.raises(OnlyResearchCalculationResultStoreError, match="RESULT_COMMIT_FAILED"):
        store.commit(sealed, graph)
    synced = []

    def record(path, **kwargs):
        sync(path, **kwargs)
        synced.append(path)

    monkeypatch.setattr(module, "_sync_directory", record)
    result = store.commit(sealed, graph)
    assert result == store.load_verified(sealed.execution.calculation_fingerprint)
    assert root.parent in synced and tmp_path in synced
    assert before == {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_v2_fresh_process_commit_reuses_exact_result(tmp_path):
    _, store, graph, sealed = _case(tmp_path)
    first = store.commit(sealed, graph)
    code = """
import json, sys
from pathlib import Path
from tests.research.calculation.test_result_v2_store import _case
_, store, graph, sealed = _case(Path(sys.argv[1]))
print(json.dumps(store.commit(sealed, graph).manifest.to_dict(), sort_keys=True))
"""
    payload = json.loads(subprocess.check_output([sys.executable, "-c", code, str(tmp_path)], text=True))
    assert payload == first.manifest.to_dict()


@pytest.mark.parametrize("chunked", (False, True))
def test_v2_store_provider_buffer_mutations_do_not_change_committed_truth(tmp_path, chunked):
    from tests.research.calculation.test_execution_readiness_v2 import _WritableBufferBackend

    backend = _WritableBufferBackend(chunked=chunked)
    _, store, graph, sealed = _case(tmp_path, _registry(backend))
    expected = [item.table.to_pydict() for item in sealed.execution.outputs]
    readiness = [item.table.to_pydict() for item in sealed.execution.readiness]
    for value in vars(backend).values():
        if isinstance(value, bytearray):
            value[:] = bytes(len(value))
    result = store.commit(sealed, graph)
    assert [item.table.to_pydict() for item in result.outputs] == expected
    assert [item.table.to_pydict() for item in result.readiness] == readiness
    assert store.commit(sealed, graph) == result


def test_v2_publication_sync_stops_at_configured_authority_parent(tmp_path, monkeypatch):
    import onlyalpha.research.calculation.result_v2_store as module

    _, store, graph, sealed = _case(tmp_path)
    root = _root(tmp_path, sealed)
    sync, calls = module._sync_directory, []

    def record(path, **kwargs):
        sync(path, **kwargs)
        calls.append(path)

    monkeypatch.setattr(module, "_sync_directory", record)
    first = store.commit(sealed, graph)
    calls.clear()  # Isolate acknowledgment from private staging sync.
    assert store.commit(sealed, graph) == first
    assert calls == [
        root / "values",
        root / "readiness",
        root,
        root.parent,
        root.parent.parent,
        root.parent.parent.parent,
        tmp_path / "results",
        tmp_path,
    ]
    assert len(calls) == len(set(calls))
    assert tmp_path.parent not in calls and Path("/") not in calls


@pytest.mark.parametrize("unknown", (False, True))
def test_v2_publication_does_not_require_unrelated_ancestor_fsync(tmp_path, monkeypatch, unknown):
    import onlyalpha.research.calculation.result_v2_store as module

    _, store, graph, sealed = _case(tmp_path)
    sync, rename, calls = module._sync_directory, module._rename_exclusive, []

    def bounded(path, **kwargs):
        calls.append(path)
        if path != tmp_path and tmp_path not in path.parents:
            raise OSError("unrelated ancestor forbids fsync")
        sync(path, **kwargs)

    def publish(stage, target):
        rename(stage, target)
        if unknown:
            raise OSError("lost rename acknowledgment")

    monkeypatch.setattr(module, "_sync_directory", bounded)
    monkeypatch.setattr(module, "_rename_exclusive", publish)
    result = store.commit(sealed, graph)
    assert store.load_verified(sealed.execution.calculation_fingerprint) == result
    assert store.commit(sealed, graph) == result
    assert all(path == tmp_path or tmp_path in path.parents for path in calls)


@pytest.mark.parametrize("failed_path", ("target-parent", "authority-root", "authority-parent"))
def test_v2_required_namespace_sync_failure_is_not_acknowledged_and_retry_converges(tmp_path, monkeypatch, failed_path):
    import onlyalpha.research.calculation.result_v2_store as module

    _, store, graph, sealed = _case(tmp_path)
    root = _root(tmp_path, sealed)
    failure = {"target-parent": root.parent, "authority-root": tmp_path / "results", "authority-parent": tmp_path}[
        failed_path
    ]
    sync = module._sync_directory

    def fail(path, **kwargs):
        if path == failure:
            raise OSError("required namespace sync unavailable")
        sync(path, **kwargs)

    monkeypatch.setattr(module, "_sync_directory", fail)
    with pytest.raises(OnlyResearchCalculationResultStoreError, match="RESULT_COMMIT_FAILED"):
        store.commit(sealed, graph)
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    monkeypatch.setattr(module, "_sync_directory", sync)
    assert store.commit(sealed, graph) == store.load_verified(sealed.execution.calculation_fingerprint)
    assert before == {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("kind", ("missing", "file", "symlink", "dangling-symlink"))
def test_v2_authority_parent_must_be_preprovisioned_real_directory(tmp_path, kind):
    executor, _, graph, sealed = _case(tmp_path)
    parent = tmp_path / "anchor"
    if kind == "file":
        parent.write_text("not a directory")
    elif kind in ("symlink", "dangling-symlink"):
        destination = tmp_path / "destination"
        if kind == "symlink":
            destination.mkdir()
        parent.symlink_to(destination, target_is_directory=True)
    store = OnlyParquetResearchCalculationResultStoreV2(
        parent / "results", executor._store.store, audit_time=lambda: AUDIT
    )
    with pytest.raises(OnlyResearchCalculationResultStoreError, match="RESULT_INVALID"):
        store.commit(sealed, graph)
    assert not (parent / "results").exists()


def test_v2_partition_identities_are_chunk_independent(tmp_path):
    _, _, _, sealed = _case(tmp_path)
    for family, is_readiness in ((sealed.execution.outputs, False), (sealed.execution.readiness, True)):
        for item in family:
            fragmented = pa.concat_tables([item.table.slice(0, 1), item.table.slice(1)])
            assert _descriptor(
                item.node_fingerprint, item.instrument_id, item.table, readiness=is_readiness
            ) == _descriptor(item.node_fingerprint, item.instrument_id, fragmented, readiness=is_readiness)
