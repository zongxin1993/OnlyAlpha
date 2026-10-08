import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.research.dataset.definition import OnlyResearchDatasetDefinition
from onlyalpha.research.dataset.identity import only_content_fingerprint, only_snapshot_fingerprint
from onlyalpha.research.dataset.lineage import (
    OnlyDatasetMaterialization,
    OnlyMarketDataRevisionBinding,
    only_dataset_materialization_id,
)
from onlyalpha.research.dataset.manifest import OnlyResearchDatasetSnapshot
from onlyalpha.research.dataset.parquet_store import (
    OnlyParquetResearchDatasetSnapshotStore,
    OnlyResearchDatasetStoreError,
)
from onlyalpha.research.dataset.schema import RESEARCH_BAR_DATASET_SCHEMA_V2
from tests.domain.conformance.support.market_data import build_bar


def _snapshot(created_at: datetime = datetime(2026, 1, 1, tzinfo=UTC)) -> tuple[OnlyResearchDatasetSnapshot, tuple]:
    bar = build_bar()
    definition = OnlyResearchDatasetDefinition(
        (bar.instrument_id,),
        bar.bar_type.semantic,
        OnlyTimeRange(bar.bar_start, bar.ts_event + timedelta(seconds=1)),
    )
    content = only_content_fingerprint((bar,))
    construction_fingerprint = "a" * 64
    fingerprint = only_snapshot_fingerprint(
        definition, RESEARCH_BAR_DATASET_SCHEMA_V2, content, 1, construction_fingerprint
    )
    return OnlyResearchDatasetSnapshot(
        definition,
        RESEARCH_BAR_DATASET_SCHEMA_V2,
        content,
        1,
        fingerprint,
        (),
        (),
        created_at,
        construction_fingerprint,
    ), ((bar,),)


def test_commit_load_verify_and_idempotent_reuse(tmp_path) -> None:
    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    snapshot, partitions = _snapshot()
    first = store.commit(snapshot, partitions)
    second = store.commit(_snapshot(datetime(2027, 1, 1, tzinfo=UTC))[0], partitions)
    assert first == second == store.load(snapshot.snapshot_fingerprint)
    assert store.load_bars(snapshot.snapshot_fingerprint) == partitions[0]
    assert store.verify(snapshot.snapshot_fingerprint).valid
    verified = store.load_verified_table(snapshot.snapshot_fingerprint)
    assert verified.snapshot == first
    assert verified.table.num_rows == 1


def test_bounded_read_preserves_same_physical_and_logical_authority(tmp_path):
    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    snapshot, partitions = _snapshot()
    store.commit(snapshot, partitions)
    bounded = store.bounded(100, 1_000_000)
    assert bounded.load_verified_table(snapshot.snapshot_fingerprint) == store.load_verified_table(
        snapshot.snapshot_fingerprint
    )
    assert bounded.verify(snapshot.snapshot_fingerprint).valid


@pytest.mark.parametrize("fault", ["stored", "rows", "decoded_metadata"])
def test_bounded_read_rejects_before_decoding_oversized_partition(tmp_path, monkeypatch, fault):
    from onlyalpha.research.dataset import parquet_store

    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    snapshot, partitions = _snapshot()
    committed = store.commit(snapshot, partitions)
    original = parquet_store.pq.ParquetFile
    opened = []

    def forbidden_decoding(raw):
        opened.append(raw)
        assert fault == "decoded_metadata", "over-budget bytes/rows must fail before Parquet parser"
        parquet = original(raw)

        class HugeMetadata:
            num_rows = 1
            num_row_groups = 1
            num_columns = parquet.metadata.num_columns

            def row_group(self, group):
                from types import SimpleNamespace

                return SimpleNamespace(column=lambda column: SimpleNamespace(total_uncompressed_size=2_000_000))

        from types import SimpleNamespace

        return SimpleNamespace(
            metadata=HugeMetadata(),
            schema_arrow=parquet.schema_arrow,
            iter_batches=lambda **kwargs: pytest.fail("over-budget metadata must fail before decoding"),
        )

    monkeypatch.setattr(parquet_store.pq, "ParquetFile", forbidden_decoding)
    if fault == "rows":
        # The persisted whole manifest is malformed, not a different valid Snapshot.
        root = store._target(committed.snapshot_fingerprint)
        raw = json.loads((root / "manifest.json").read_text())
        raw["row_count"] = 101
        (root / "manifest.json").write_text(json.dumps(raw))
    budget = 1 if fault == "stored" else 1_000_000
    with pytest.raises(OnlyResearchDatasetStoreError):
        store.bounded(100, budget).load_verified_table(snapshot.snapshot_fingerprint)
    assert bool(opened) is (fault == "decoded_metadata")


def test_bounded_read_requires_nested_partition_rows_to_close_before_decoding(tmp_path, monkeypatch):
    import hashlib

    import pyarrow as pa
    import pyarrow.parquet as pq

    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    snapshot, partitions = _snapshot()
    committed = store.commit(snapshot, partitions)
    root = store._target(committed.snapshot_fingerprint)
    original = store.load_verified_table(committed.snapshot_fingerprint).table
    partition = committed.partitions[0]
    target = root / partition.relative_path
    pq.write_table(pa.concat_tables([original, original]), target)
    nested = replace(partition, row_count=2, byte_sha256=hashlib.sha256(target.read_bytes()).hexdigest())
    mutated = replace(committed, partitions=(nested,))
    # Global fingerprint and global row count are valid and unchanged; only the
    # relevant nested relation is incomplete/different. Hash rejection is not proof.
    assert (
        OnlyResearchDatasetSnapshot.from_dict(mutated.to_dict()).snapshot_fingerprint == committed.snapshot_fingerprint
    )
    (root / "manifest.json").write_text(json.dumps(mutated.to_dict()))
    monkeypatch.setattr(
        pq, "ParquetFile", lambda *args, **kwargs: pytest.fail("nested row proof must close before decoding")
    )
    with pytest.raises(OnlyResearchDatasetStoreError, match="DATASET_READ_RESOURCE_LIMIT"):
        store.bounded(1, 1_000_000).load_verified_table(committed.snapshot_fingerprint)


def test_bounded_manifest_bytes_are_checked_before_json_parse(tmp_path, monkeypatch):
    from onlyalpha.research.dataset import parquet_store

    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    snapshot, partitions = _snapshot()
    store.commit(snapshot, partitions)
    monkeypatch.setattr(
        parquet_store.json, "loads", lambda *args: pytest.fail("over-budget manifest must not be parsed")
    )
    with pytest.raises(OnlyResearchDatasetStoreError):
        store.bounded(1, 1).load(snapshot.snapshot_fingerprint)
    with pytest.raises(OnlyResearchDatasetStoreError):
        store.bounded(1, 1).load_verified_table(snapshot.snapshot_fingerprint)


def test_materialization_lineage_is_immutable_and_idempotent(tmp_path) -> None:
    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    snapshot, _ = _snapshot()
    bindings = (
        OnlyMarketDataRevisionBinding(
            "BINANCE_SPOT",
            "BTCUSDT.BINANCE",
            "BAR",
            "market-data-revision:r1",
            "a" * 64,
        ),
    )
    materialization_id = only_dataset_materialization_id(
        snapshot.snapshot_fingerprint,
        bindings,
        "onlyalpha.sealed-market-data",
        "1",
        "b" * 64,
    )
    value = OnlyDatasetMaterialization(
        materialization_id,
        snapshot.snapshot_fingerprint,
        bindings,
        "onlyalpha.sealed-market-data",
        "1",
        "b" * 64,
        datetime(2026, 1, 1, tzinfo=UTC),
    )
    first = store.commit_materialization(value)
    second = store.commit_materialization(replace(value, created_at=datetime(2027, 1, 1, tzinfo=UTC)))
    assert first == second == store.load_materialization(materialization_id)


def test_tampered_partition_and_manifest_fail_closed_without_overwrite(tmp_path) -> None:
    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    snapshot, partitions = _snapshot()
    committed = store.commit(snapshot, partitions)
    root = tmp_path / "sha256" / committed.snapshot_fingerprint[:2] / committed.snapshot_fingerprint
    partition = root / committed.partitions[0].relative_path
    partition.write_bytes(partition.read_bytes() + b"tamper")
    with pytest.raises(OnlyResearchDatasetStoreError, match="CORRUPT"):
        store.verify(committed.snapshot_fingerprint)
    with pytest.raises(OnlyResearchDatasetStoreError, match="CORRUPT"):
        store.commit(snapshot, partitions)


def test_strict_manifest_rejects_unknown_field(tmp_path) -> None:
    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    snapshot, partitions = _snapshot()
    committed = store.commit(snapshot, partitions)
    root = tmp_path / "sha256" / committed.snapshot_fingerprint[:2] / committed.snapshot_fingerprint
    manifest = root / "manifest.json"
    payload = json.loads(manifest.read_text())
    payload["unknown"] = True
    manifest.write_text(json.dumps(payload))
    with pytest.raises(OnlyResearchDatasetStoreError, match="CORRUPT"):
        store.load(committed.snapshot_fingerprint)


def test_old_manifest_requires_dataset_rebuild() -> None:
    snapshot, _ = _snapshot()
    payload = snapshot.to_dict()
    payload["schema_version"] = 1

    with pytest.raises(ValueError, match="DATASET_REBUILD_REQUIRED"):
        OnlyResearchDatasetSnapshot.from_dict(payload)


def test_storage_codec_options_do_not_change_snapshot_identity(tmp_path) -> None:
    snapshot, partitions = _snapshot()
    first = OnlyParquetResearchDatasetSnapshotStore(tmp_path / "a", compression="zstd", row_group_size=1).commit(
        snapshot, partitions
    )
    second = OnlyParquetResearchDatasetSnapshotStore(tmp_path / "b", compression="snappy", row_group_size=100).commit(
        snapshot, partitions
    )
    assert first.snapshot_fingerprint == second.snapshot_fingerprint
    assert first.partitions[0].byte_sha256 != second.partitions[0].byte_sha256


def test_partition_layout_does_not_change_snapshot_identity(tmp_path) -> None:
    snapshot, partitions = _snapshot()
    bar = partitions[0][0]
    later = replace(
        bar,
        bar_start=bar.bar_start + timedelta(minutes=1),
        bar_end=bar.bar_end + timedelta(minutes=1),
        ts_event=bar.ts_event + timedelta(minutes=1),
        ts_init=bar.ts_init + timedelta(minutes=1),
    )
    content = only_content_fingerprint((bar, later))
    fingerprint = only_snapshot_fingerprint(
        snapshot.definition, snapshot.dataset_schema, content, 2, snapshot.construction_fingerprint
    )
    updated = replace(snapshot, content_fingerprint=content, row_count=2, snapshot_fingerprint=fingerprint)
    one = OnlyParquetResearchDatasetSnapshotStore(tmp_path / "one").commit(updated, ((bar, later),))
    two = OnlyParquetResearchDatasetSnapshotStore(tmp_path / "two").commit(updated, ((bar,), (later,)))
    assert one.snapshot_fingerprint == two.snapshot_fingerprint


def test_concurrent_same_snapshot_commit_has_one_authority(tmp_path) -> None:
    snapshot, partitions = _snapshot()
    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _: store.commit(snapshot, partitions), range(2)))
    assert results[0].snapshot_fingerprint == results[1].snapshot_fingerprint
    target = tmp_path / "sha256" / snapshot.snapshot_fingerprint[:2]
    assert [path.name for path in target.iterdir() if not path.name.startswith(".stage-")] == [
        snapshot.snapshot_fingerprint
    ]


def test_failure_before_final_rename_leaves_snapshot_invisible(tmp_path, monkeypatch) -> None:
    snapshot, partitions = _snapshot()
    store = OnlyParquetResearchDatasetSnapshotStore(tmp_path)
    import onlyalpha.research.dataset.parquet_store as module

    monkeypatch.setattr(module.os, "rename", lambda source, target: (_ for _ in ()).throw(OSError("injected")))
    with pytest.raises(OnlyResearchDatasetStoreError, match="COMMIT_FAILED"):
        store.commit(snapshot, partitions)
    assert not store.exists(snapshot.snapshot_fingerprint)
