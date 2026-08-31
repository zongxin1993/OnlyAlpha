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
from onlyalpha.research.dataset.schema import RESEARCH_BAR_DATASET_SCHEMA_V1
from tests.domain_conformance.support.market_data import build_bar


def _snapshot(created_at: datetime = datetime(2026, 1, 1, tzinfo=UTC)) -> tuple[OnlyResearchDatasetSnapshot, tuple]:
    bar = build_bar()
    definition = OnlyResearchDatasetDefinition(
        (bar.instrument_id,),
        bar.bar_type.specification,
        bar.bar_type.aggregation_source,
        OnlyTimeRange(bar.bar_start, bar.ts_event + timedelta(seconds=1)),
    )
    content = only_content_fingerprint((bar,))
    fingerprint = only_snapshot_fingerprint(definition, RESEARCH_BAR_DATASET_SCHEMA_V1, content, 1)
    return OnlyResearchDatasetSnapshot(
        definition, RESEARCH_BAR_DATASET_SCHEMA_V1, content, 1, fingerprint, (), (), created_at
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
    fingerprint = only_snapshot_fingerprint(snapshot.definition, snapshot.dataset_schema, content, 2)
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
