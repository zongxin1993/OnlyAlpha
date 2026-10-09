"""Lossless Dataset semantics and explicit owning durability acknowledgement."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.research.dataset.identity import only_snapshot_fingerprint
from onlyalpha.research.dataset.parquet_store import (
    OnlyParquetResearchDatasetSnapshotStore,
    OnlyResearchDatasetStoreError,
)
from tests.research.dataset.test_store_contract import _snapshot

pytestmark = pytest.mark.contract


@pytest.mark.parametrize("bounded", (False, True))
def test_verified_read_rejects_subprecision_arrow_value_even_when_bar_hash_is_unchanged(tmp_path, bounded):
    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    snapshot, partitions = _snapshot()
    committed = store.commit(snapshot, partitions)
    root = store._target(committed.snapshot_fingerprint)
    path = root / committed.partitions[0].relative_path
    table = pq.read_table(path)
    values = table["close"].to_pylist()
    values[0] += Decimal("1E-18")
    table = table.set_column(
        table.schema.get_field_index("close"), table.schema.field("close"), pa.array(values, type=table["close"].type)
    )
    pq.write_table(table, path)
    mutated = replace(
        committed,
        partitions=(replace(committed.partitions[0], byte_sha256=hashlib.sha256(path.read_bytes()).hexdigest()),),
    )
    (root / "manifest.json").write_text(json.dumps(mutated.to_dict()))
    reader = store.bounded(100, 1_000_000) if bounded else store
    with pytest.raises(OnlyResearchDatasetStoreError, match="CORRUPT"):
        reader.load_verified_table(committed.snapshot_fingerprint)


def test_rehashed_definition_still_must_cover_the_retained_bars(tmp_path):
    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    snapshot, partitions = _snapshot()
    committed = store.commit(snapshot, partitions)
    definition = replace(
        committed.definition,
        time_range=OnlyTimeRange(
            committed.definition.time_range.start + timedelta(days=365),
            committed.definition.time_range.end + timedelta(days=365),
        ),
    )
    identity = only_snapshot_fingerprint(
        definition,
        committed.dataset_schema,
        committed.content_fingerprint,
        committed.row_count,
        committed.construction_fingerprint,
    )
    mutated = replace(committed, definition=definition, snapshot_fingerprint=identity)
    root = store._target(committed.snapshot_fingerprint)
    target = store._target(identity)
    target.parent.mkdir(parents=True, exist_ok=True)
    root.rename(target)
    (target / "manifest.json").write_text(json.dumps(mutated.to_dict()))
    with pytest.raises(OnlyResearchDatasetStoreError, match="CORRUPT"):
        store.load_verified_table(identity)


@pytest.mark.parametrize("site", ("file", "data", "snapshot", "prefix", "sha256", "root", "anchor"))
def test_dataset_acknowledgement_syncs_every_owned_link_and_failures_propagate(tmp_path, monkeypatch, site):
    from onlyalpha.research.dataset import parquet_store

    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    snapshot, partitions = _snapshot()
    committed = store.commit(snapshot, partitions)
    target = store._target(committed.snapshot_fingerprint)
    before = {path: path.read_bytes() for path in target.rglob("*") if path.is_file()}
    original = parquet_store.os.fsync
    touched = []

    def unavailable(descriptor):
        # Test only: identify the opened descriptor on Linux/macOS using stat
        # identity, without assuming /proc availability on the host.
        opened = os.fstat(descriptor)
        candidates = (*before, target / "data", target, target.parent, target.parent.parent, tmp_path, tmp_path.parent)
        actual = next(
            (path for path in candidates if (path.stat().st_dev, path.stat().st_ino) == (opened.st_dev, opened.st_ino)),
            None,
        )
        if actual is None:
            original(descriptor)
            return
        touched.append(actual)
        selected = {
            "data": target / "data",
            "snapshot": target,
            "prefix": target.parent,
            "sha256": target.parent.parent,
            "root": tmp_path,
            "anchor": tmp_path.parent,
        }.get(site)
        if (site == "file" and actual.is_file()) or actual == selected:
            raise OSError("controlled Dataset predecessor sync failure")
        original(descriptor)

    monkeypatch.setattr(parquet_store.os, "fsync", unavailable)
    with pytest.raises(OnlyResearchDatasetStoreError, match="ACKNOWLEDGEMENT_FAILED"):
        store.acknowledge_exact(committed.snapshot_fingerprint)
    assert touched
    assert store.load_verified_table(committed.snapshot_fingerprint).snapshot == committed
    assert before == {path: path.read_bytes() for path in target.rglob("*") if path.is_file()}
    monkeypatch.setattr(parquet_store.os, "fsync", original)
    assert store.acknowledge_exact(committed.snapshot_fingerprint).snapshot == committed


def test_readonly_dataset_load_never_issues_durability_acknowledgement(tmp_path, monkeypatch):
    from onlyalpha.research.dataset import parquet_store

    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    snapshot, partitions = _snapshot()
    committed = store.commit(snapshot, partitions)
    monkeypatch.setattr(parquet_store.os, "fsync", lambda *_: pytest.fail("ordinary verified read attempted fsync"))
    assert store.load_verified_table(committed.snapshot_fingerprint).snapshot == committed


def test_new_dataset_root_link_requires_its_own_preprovisioned_parent_acknowledgement(tmp_path, monkeypatch):
    from onlyalpha.research.dataset import parquet_store

    anchor = tmp_path / "independent-dataset-parent"
    anchor.mkdir()
    store = OnlyParquetResearchDatasetSnapshotStore(anchor / "new-dataset-root")
    snapshot, partitions = _snapshot()
    committed = store.commit(snapshot, partitions)
    sync = parquet_store.os.fsync
    touched = []

    def unavailable(descriptor):
        actual, expected = os.fstat(descriptor), anchor.stat()
        if (actual.st_dev, actual.st_ino) == (expected.st_dev, expected.st_ino):
            touched.append(anchor)
            raise OSError("controlled newly-created Dataset root link failure")
        sync(descriptor)

    monkeypatch.setattr(parquet_store.os, "fsync", unavailable)
    with pytest.raises(OnlyResearchDatasetStoreError, match="ACKNOWLEDGEMENT_FAILED"):
        store.acknowledge_exact(committed.snapshot_fingerprint)
    assert touched == [anchor]
    monkeypatch.undo()
    assert store.acknowledge_exact(committed.snapshot_fingerprint).snapshot == committed


def test_acknowledgement_covers_parent_links_created_by_legacy_commit(tmp_path, monkeypatch):
    from onlyalpha.research.dataset import parquet_store

    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path / "unprovisioned-anchor" / "dataset")
    snapshot, partitions = _snapshot()
    committed = store.commit(snapshot, partitions)
    original = parquet_store.os.fsync
    touched = set()

    def record(descriptor):
        opened = os.fstat(descriptor)
        touched.add((opened.st_dev, opened.st_ino))
        original(descriptor)

    monkeypatch.setattr(parquet_store.os, "fsync", record)
    assert store.acknowledge_exact(committed.snapshot_fingerprint).snapshot == committed
    for path in (store._root, *store._root.absolute().parents):
        assert (path.stat().st_dev, path.stat().st_ino) in touched


@pytest.mark.parametrize(
    "mutation",
    ("root", "sha256", "prefix", "snapshot", "data", "manifest", "partition", "extra_file", "extra_directory"),
)
def test_dataset_acknowledgement_rejects_namespace_substitution_during_sync(tmp_path, monkeypatch, mutation):
    from onlyalpha.research.dataset import parquet_store

    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path / "dataset")
    snapshot, partitions = _snapshot()
    committed = store.commit(snapshot, partitions)
    target = store._target(committed.snapshot_fingerprint)
    snapshot_inode = (target.stat().st_dev, target.stat().st_ino)
    sync = parquet_store.os.fsync
    touched = []

    def substitute(descriptor):
        sync(descriptor)
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != snapshot_inode or touched:
            return
        touched.append(mutation)
        if mutation == "extra_file":
            (target / "unexpected.json").write_text("{}")
        elif mutation == "extra_directory":
            (target / "unexpected").mkdir()
        else:
            path = {
                "root": tmp_path / "dataset",
                "sha256": target.parent.parent,
                "prefix": target.parent,
                "snapshot": target,
                "data": target / "data",
                "manifest": target / "manifest.json",
                "partition": target / committed.partitions[0].relative_path,
            }[mutation]
            moved = tmp_path / "substituted-retained-entry"
            path.rename(moved)
            if mutation in {"manifest", "partition"}:
                # A complete byte-identical regular replacement is still a new
                # inode whose durability was not proved by syncing the old file.
                path.write_bytes(moved.read_bytes())
            else:
                path.symlink_to(moved, target_is_directory=True)

    monkeypatch.setattr(parquet_store.os, "fsync", substitute)
    with pytest.raises(OnlyResearchDatasetStoreError, match="ACKNOWLEDGEMENT_FAILED"):
        store.acknowledge_exact(committed.snapshot_fingerprint)
    assert touched == [mutation]
