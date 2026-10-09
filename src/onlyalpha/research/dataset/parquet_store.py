"""Atomic immutable content-addressed Parquet Dataset Snapshot store."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import uuid
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from onlyalpha.domain.market import OnlyBar

from .codec import only_bars_to_table, only_table_to_bars
from .definition import OnlyResearchDatasetDefinition
from .identity import only_canonical_bars, only_content_fingerprint, only_snapshot_fingerprint
from .lineage import (
    OnlyDatasetMaterialization,
    OnlyMarketDataRevisionBinding,
)
from .manifest import (
    OnlyResearchDatasetPartitionManifest,
    OnlyResearchDatasetSnapshot,
)
from .ports import OnlyResearchDatasetVerification, OnlyVerifiedResearchDataset
from .schema import RESEARCH_BAR_DATASET_SCHEMA_V2
from .validation import only_validate_dataset_bars


class OnlyResearchDatasetStoreError(RuntimeError):
    pass


class OnlyResearchDatasetNotFoundError(OnlyResearchDatasetStoreError):
    code = "DATASET_SNAPSHOT_NOT_FOUND"


class OnlyResearchDatasetCorruptError(OnlyResearchDatasetStoreError):
    code = "DATASET_SNAPSHOT_CORRUPT"


class OnlyParquetResearchDatasetSnapshotStore:
    def __init__(
        self,
        root: Path,
        *,
        compression: str = "zstd",
        row_group_size: int | None = None,
        read_budget: tuple[int, int] | None = None,
    ) -> None:
        self._root = root
        self._compression = compression
        self._row_group_size = row_group_size
        if read_budget is not None and (
            type(read_budget) is not tuple
            or len(read_budget) != 2
            or any(type(value) is not int or value < 1 for value in read_budget)
        ):
            raise ValueError("DATASET_READ_BUDGET_INVALID")
        self._read_budget = read_budget

    def bounded(self, max_rows: int, max_bytes: int) -> OnlyParquetResearchDatasetSnapshotStore:
        return OnlyParquetResearchDatasetSnapshotStore(
            self._root,
            compression=self._compression,
            row_group_size=self._row_group_size,
            read_budget=(max_rows, max_bytes),
        )

    def exists(self, snapshot_fingerprint: str) -> bool:
        return self._target(snapshot_fingerprint).exists()

    def commit_materialization(self, value: OnlyDatasetMaterialization) -> OnlyDatasetMaterialization:
        target = self._materialization_target(value.materialization_id)
        if target.exists():
            prior = self.load_materialization(value.materialization_id)
            if prior.semantic_payload() != value.semantic_payload():
                raise OnlyResearchDatasetStoreError("DATASET_MATERIALIZATION_IDENTITY_CONFLICT")
            return prior
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = target.parent / f".stage-{uuid.uuid4().hex}.json"
        payload = {
            "schema_version": 1,
            "materialization_id": value.materialization_id,
            "dataset_snapshot_fingerprint": value.dataset_snapshot_fingerprint,
            "market_data_revision_bindings": [
                {
                    "source_id": item.source_id,
                    "instrument_id": item.instrument_id,
                    "data_kind": item.data_kind,
                    "revision_id": item.revision_id,
                    "revision_fingerprint": item.revision_fingerprint,
                }
                for item in value.market_data_revision_bindings
            ],
            "materializer_id": value.materializer_id,
            "materializer_version": value.materializer_version,
            "request_fingerprint": value.request_fingerprint,
            "created_at": value.created_at.isoformat(),
        }
        try:
            with stage.open("xb") as stream:
                stream.write(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(stage, target)
                _fsync_directory(target.parent)
            except OSError:
                if not target.exists():
                    raise
            prior = self.load_materialization(value.materialization_id)
            if prior.semantic_payload() != value.semantic_payload():
                raise OnlyResearchDatasetStoreError("DATASET_MATERIALIZATION_IDENTITY_CONFLICT")
            return prior
        finally:
            stage.unlink(missing_ok=True)

    def load_materialization(self, materialization_id: str) -> OnlyDatasetMaterialization:
        path = self._materialization_target(materialization_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("schema_version") != 1:
                raise ValueError("materialization schema")
            raw_bindings = payload["market_data_revision_bindings"]
            if not isinstance(raw_bindings, list):
                raise ValueError("materialization bindings")
            bindings = tuple(
                OnlyMarketDataRevisionBinding(
                    str(item["source_id"]),
                    str(item["instrument_id"]),
                    str(item["data_kind"]),
                    str(item["revision_id"]),
                    str(item["revision_fingerprint"]),
                )
                for item in raw_bindings
                if isinstance(item, dict)
            )
            if len(bindings) != len(raw_bindings):
                raise ValueError("materialization binding shape")
            return OnlyDatasetMaterialization(
                str(payload["materialization_id"]),
                str(payload["dataset_snapshot_fingerprint"]),
                bindings,
                str(payload["materializer_id"]),
                str(payload["materializer_version"]),
                str(payload["request_fingerprint"]),
                datetime.fromisoformat(str(payload["created_at"])),
            )
        except Exception as exc:
            raise OnlyResearchDatasetCorruptError("DATASET_MATERIALIZATION_CORRUPT") from exc

    def commit(
        self,
        snapshot: OnlyResearchDatasetSnapshot,
        partitions: tuple[tuple[OnlyBar, ...], ...],
    ) -> OnlyResearchDatasetSnapshot:
        target = self._target(snapshot.snapshot_fingerprint)
        if target.exists():
            self.verify(snapshot.snapshot_fingerprint)
            return self.load(snapshot.snapshot_fingerprint)
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = target.parent / f".stage-{uuid.uuid4().hex}"
        stage.mkdir()
        try:
            manifests: list[OnlyResearchDatasetPartitionManifest] = []
            for index, bars in enumerate(partitions):
                relative = f"data/p-{index:06d}.parquet"
                path = stage / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                canonical = only_canonical_bars(bars)
                pq.write_table(
                    only_bars_to_table(canonical),
                    path,
                    compression=self._compression,
                    row_group_size=self._row_group_size,
                )
                restored = only_table_to_bars(pq.read_table(path))
                if restored != canonical:
                    raise OnlyResearchDatasetStoreError("DATASET_SNAPSHOT_COMMIT_FAILED: Parquet round-trip")
                manifests.append(
                    OnlyResearchDatasetPartitionManifest(
                        f"p-{index:06d}",
                        len(canonical),
                        only_content_fingerprint(canonical),
                        relative,
                        _sha(path),
                    )
                )
            committed = OnlyResearchDatasetSnapshot(
                snapshot.definition,
                snapshot.dataset_schema,
                snapshot.content_fingerprint,
                snapshot.row_count,
                snapshot.snapshot_fingerprint,
                tuple(manifests),
                snapshot.provenance,
                snapshot.created_at,
                snapshot.construction_fingerprint,
            )
            (stage / "manifest.json").write_text(
                json.dumps(committed.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            self._verify_root(stage, snapshot.snapshot_fingerprint)
            try:
                os.rename(stage, target)
            except OSError:
                if not target.exists():
                    raise
                self.verify(snapshot.snapshot_fingerprint)
                return self.load(snapshot.snapshot_fingerprint)
            return committed
        except OnlyResearchDatasetStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchDatasetStoreError("DATASET_SNAPSHOT_COMMIT_FAILED") from exc
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def load(self, snapshot_fingerprint: str) -> OnlyResearchDatasetSnapshot:
        target = self._target(snapshot_fingerprint)
        if not target.is_dir():
            raise OnlyResearchDatasetNotFoundError("DATASET_SNAPSHOT_NOT_FOUND")
        try:
            return self._load_manifest(target)[0]
        except Exception as exc:
            raise OnlyResearchDatasetCorruptError("DATASET_SNAPSHOT_CORRUPT: manifest") from exc

    def _load_manifest(
        self, root: Path, retained_descriptors: Mapping[str, int] | None = None
    ) -> tuple[OnlyResearchDatasetSnapshot, int]:
        if retained_descriptors is not None:
            raw = _read_descriptor(
                retained_descriptors["manifest.json"], None if self._read_budget is None else self._read_budget[1]
            )
            manifest_bytes = len(raw) if self._read_budget is not None else 0
            if self._read_budget is not None and manifest_bytes > self._read_budget[1]:
                raise OnlyResearchDatasetStoreError("DATASET_READ_RESOURCE_LIMIT")
            text = raw.decode("utf-8")
        elif self._read_budget is None:
            text = (root / "manifest.json").read_text(encoding="utf-8")
            manifest_bytes = 0
        else:
            with (root / "manifest.json").open("rb") as stream:
                raw = stream.read(self._read_budget[1] + 1)
            manifest_bytes = len(raw)
            if manifest_bytes > self._read_budget[1]:
                raise OnlyResearchDatasetStoreError("DATASET_READ_RESOURCE_LIMIT")
            text = raw.decode("utf-8")
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("manifest must be an object")
        return OnlyResearchDatasetSnapshot.from_dict(payload), manifest_bytes

    def load_bars(self, snapshot_fingerprint: str) -> tuple[OnlyBar, ...]:
        snapshot = self.load(snapshot_fingerprint)
        target = self._target(snapshot_fingerprint)
        bars: list[OnlyBar] = []
        for partition in snapshot.partitions:
            bars.extend(only_table_to_bars(pq.read_table(target / partition.relative_path)))
        return only_canonical_bars(tuple(bars))

    def load_verified_table(self, snapshot_fingerprint: str) -> OnlyVerifiedResearchDataset:
        """Verify every durable authority before exposing one canonical Arrow table."""

        _, snapshot, table = self._read_verified(self._target(snapshot_fingerprint), snapshot_fingerprint)
        return OnlyVerifiedResearchDataset(snapshot, table)

    def resolve_verified(self, definition: OnlyResearchDatasetDefinition) -> OnlyVerifiedResearchDataset:
        """Resolve one exact Definition only when the immutable Store proves a unique Snapshot."""

        roots = () if not (self._root / "sha256").is_dir() else tuple(sorted((self._root / "sha256").glob("*/*")))
        matches: list[OnlyVerifiedResearchDataset] = []
        for root in roots:
            if not root.is_dir():
                continue
            verified = self.load_verified_table(root.name)
            if verified.snapshot.definition == definition:
                matches.append(verified)
        if not matches:
            raise OnlyResearchDatasetNotFoundError("DATASET_SNAPSHOT_NOT_FOUND")
        if len(matches) != 1:
            raise OnlyResearchDatasetStoreError("DATASET_SNAPSHOT_AMBIGUOUS")
        return matches[0]

    def verify(self, snapshot_fingerprint: str) -> OnlyResearchDatasetVerification:
        verification, _, _ = self._read_verified(self._target(snapshot_fingerprint), snapshot_fingerprint)
        return verification

    def acknowledge_exact(self, snapshot_fingerprint: str) -> OnlyVerifiedResearchDataset:
        """Explicit owning durability acknowledgement; ordinary reads remain read-only."""
        target = self._target(snapshot_fingerprint)
        descriptors: list[int] = []
        try:
            root = self._root.absolute()
            # The filesystem root is the fixed preprovisioned anchor across
            # restarts. A merely existing Store parent may itself be unsynced.
            anchor = Path(root.anchor)
            anchor_descriptor = os.open(anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            descriptors.append(anchor_descriptor)
            directories = [anchor_descriptor]
            # Every traversed name is bound to its opened no-follow inode. Sync
            # those descriptors, never a path that can redirect through a symlink.
            bindings: list[tuple[int, str, int]] = []
            parent = anchor_descriptor
            for name in (*root.parts[1:], "sha256", snapshot_fingerprint[:2], snapshot_fingerprint):
                descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                descriptors.append(descriptor)
                directories.append(descriptor)
                bindings.append((parent, name, descriptor))
                parent = descriptor
            snapshot_descriptor = parent
            manifest_descriptor = os.open("manifest.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            descriptors.append(manifest_descriptor)
            bindings.append((parent, "manifest.json", manifest_descriptor))
            if not stat.S_ISREG(os.fstat(manifest_descriptor).st_mode):
                raise ValueError("Dataset manifest must be a regular file")
            retained = {"manifest.json": manifest_descriptor}
            snapshot, _ = self._load_manifest(target, retained)
            for index, partition in enumerate(snapshot.partitions):
                if (
                    partition.partition_id != f"p-{index:06d}"
                    or partition.relative_path != f"data/p-{index:06d}.parquet"
                ):
                    raise ValueError("Dataset acknowledgement requires canonical partition paths")
            data_descriptor = None
            if snapshot.partitions:
                data_descriptor = os.open("data", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                descriptors.append(data_descriptor)
                directories.append(data_descriptor)
                bindings.append((parent, "data", data_descriptor))
                for partition in snapshot.partitions:
                    name = Path(partition.relative_path).name
                    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=data_descriptor)
                    descriptors.append(descriptor)
                    bindings.append((data_descriptor, name, descriptor))
                    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                        raise ValueError("Dataset partition must be a regular file")
                    retained[partition.relative_path] = descriptor

            def require_namespace() -> None:
                for parent_fd, name, opened_fd in bindings:
                    actual = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                    expected = os.fstat(opened_fd)
                    if (actual.st_dev, actual.st_ino, stat.S_IFMT(actual.st_mode)) != (
                        expected.st_dev,
                        expected.st_ino,
                        stat.S_IFMT(expected.st_mode),
                    ):
                        raise ValueError("Dataset namespace changed during acknowledgement")
                # Timestamps may change as peers publish under the shared anchor;
                # only exact inode/type identity binds this deployment boundary.
                actual, expected = os.stat(anchor, follow_symlinks=False), os.fstat(anchor_descriptor)
                if (actual.st_dev, actual.st_ino, stat.S_IFMT(actual.st_mode)) != (
                    expected.st_dev,
                    expected.st_ino,
                    stat.S_IFMT(expected.st_mode),
                ):
                    raise ValueError("Dataset durability anchor changed")
                expected_entries = {"manifest.json", "data"} if data_descriptor is not None else {"manifest.json"}
                if set(os.listdir(snapshot_descriptor)) != expected_entries:
                    raise ValueError("Dataset exact file/directory set differs")
                if data_descriptor is not None and set(os.listdir(data_descriptor)) != {
                    Path(part.relative_path).name for part in snapshot.partitions
                }:
                    raise ValueError("Dataset partition file set differs")

            require_namespace()
            _, verified_snapshot, verified_table = self._read_verified(target, snapshot_fingerprint, retained)
            for descriptor in retained.values():
                os.fsync(descriptor)
            # Acknowledge all ancestor links through the fixed filesystem anchor;
            # ordinary commit keeps its existing directory-creation behavior.
            for descriptor in reversed(directories):
                os.fsync(descriptor)
            require_namespace()
            _, reloaded_snapshot, reloaded_table = self._read_verified(target, snapshot_fingerprint, retained)
            require_namespace()
            if reloaded_snapshot != verified_snapshot or not reloaded_table.equals(verified_table, check_metadata=True):
                raise ValueError("Dataset changed during durability acknowledgement")
            return OnlyVerifiedResearchDataset(reloaded_snapshot, reloaded_table)
        except Exception as exc:
            raise OnlyResearchDatasetStoreError("DATASET_SNAPSHOT_ACKNOWLEDGEMENT_FAILED") from exc
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)

    def _verify_root(self, root: Path, expected_fingerprint: str) -> OnlyResearchDatasetVerification:
        verification, _, _ = self._read_verified(root, expected_fingerprint)
        return verification

    def _read_verified(
        self, root: Path, expected_fingerprint: str, retained_descriptors: Mapping[str, int] | None = None
    ) -> tuple[OnlyResearchDatasetVerification, OnlyResearchDatasetSnapshot, pa.Table]:
        if retained_descriptors is None and not root.is_dir():
            raise OnlyResearchDatasetNotFoundError("DATASET_SNAPSHOT_NOT_FOUND")
        try:
            snapshot, manifest_bytes = self._load_manifest(root, retained_descriptors)
            if snapshot.snapshot_fingerprint != expected_fingerprint:
                raise ValueError("snapshot path identity mismatch")
            if self._read_budget is not None:
                if (
                    snapshot.row_count > self._read_budget[0]
                    or sum(item.row_count for item in snapshot.partitions) != snapshot.row_count
                ):
                    raise OnlyResearchDatasetStoreError("DATASET_READ_RESOURCE_LIMIT")
            bars: list[OnlyBar] = []
            tables: list[pa.Table] = []
            total = 0
            stored_bytes, decoded_bytes = manifest_bytes, 0
            logical_bytes = decoded_rows = 0
            for partition in snapshot.partitions:
                path = root / partition.relative_path
                if self._read_budget is None:
                    if retained_descriptors is None:
                        if not path.is_file() or _sha(path) != partition.byte_sha256:
                            raise ValueError("partition byte hash mismatch")
                        table = pq.read_table(path)
                    else:
                        raw = _read_descriptor(retained_descriptors[partition.relative_path], None)
                        if hashlib.sha256(raw).hexdigest() != partition.byte_sha256:
                            raise ValueError("partition byte hash mismatch")
                        table = pq.read_table(pa.BufferReader(raw))
                else:
                    # Freeze bounded physical bytes before inspecting metadata or
                    # decoding. A path mutation cannot swap a different payload in.
                    remaining = self._read_budget[1] - stored_bytes
                    if retained_descriptors is None:
                        with path.open("rb") as stream:
                            raw = stream.read(remaining + 1)
                    else:
                        raw = _read_descriptor(retained_descriptors[partition.relative_path], remaining)
                    stored_bytes += len(raw)
                    if stored_bytes > self._read_budget[1]:
                        raise OnlyResearchDatasetStoreError("DATASET_READ_RESOURCE_LIMIT")
                    if hashlib.sha256(raw).hexdigest() != partition.byte_sha256:
                        raise ValueError("partition byte hash mismatch")
                    parquet = pq.ParquetFile(pa.BufferReader(raw))
                    metadata = parquet.metadata
                    if (
                        metadata.num_rows != partition.row_count
                        or parquet.schema_arrow != snapshot.dataset_schema.arrow_schema
                    ):
                        raise ValueError("partition predecode schema/rows mismatch")
                    decoded_bytes += sum(
                        metadata.row_group(group).column(column).total_uncompressed_size
                        for group in range(metadata.num_row_groups)
                        for column in range(metadata.num_columns)
                    )
                    if decoded_bytes > self._read_budget[1]:
                        raise OnlyResearchDatasetStoreError("DATASET_READ_RESOURCE_LIMIT")
                    batches = []
                    # A dictionary can expand far beyond encoded page bytes. Bound
                    # expansion incrementally before constructing a whole table.
                    for batch in parquet.iter_batches(batch_size=1):
                        logical_bytes += batch.nbytes
                        decoded_rows += batch.num_rows
                        if logical_bytes > self._read_budget[1] or decoded_rows > self._read_budget[0]:
                            raise OnlyResearchDatasetStoreError("DATASET_READ_RESOURCE_LIMIT")
                        batches.append(batch)
                    table = pa.Table.from_batches(batches, schema=parquet.schema_arrow)
                restored = only_table_to_bars(table)
                if not table.equals(only_bars_to_table(restored), check_metadata=True):
                    raise ValueError("Dataset partition is not a lossless canonical Bar representation")
                if len(restored) != partition.row_count:
                    raise ValueError("partition row count mismatch")
                if only_content_fingerprint(restored) != partition.semantic_fingerprint:
                    raise ValueError("partition semantic fingerprint mismatch")
                total += len(restored)
                bars.extend(restored)
                tables.append(table)
            if total != snapshot.row_count or only_content_fingerprint(tuple(bars)) != snapshot.content_fingerprint:
                raise ValueError("global content mismatch")
            only_validate_dataset_bars(snapshot.definition, tuple(bars))
            if (
                only_snapshot_fingerprint(
                    snapshot.definition,
                    snapshot.dataset_schema,
                    snapshot.content_fingerprint,
                    snapshot.row_count,
                    snapshot.construction_fingerprint,
                )
                != snapshot.snapshot_fingerprint
            ):
                raise ValueError("snapshot semantic fingerprint mismatch")
            table = (
                pa.concat_tables(tables)
                if tables
                else pa.Table.from_pylist([], schema=RESEARCH_BAR_DATASET_SCHEMA_V2.arrow_schema)
            )
            if table.schema != snapshot.dataset_schema.arrow_schema or table.num_rows != snapshot.row_count:
                raise ValueError("verified table mismatch")
            return (
                OnlyResearchDatasetVerification(True, snapshot.snapshot_fingerprint, snapshot.row_count),
                snapshot,
                table,
            )
        except OnlyResearchDatasetStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchDatasetCorruptError("DATASET_SNAPSHOT_CORRUPT") from exc

    def _target(self, fingerprint: str) -> Path:
        if len(fingerprint) != 64 or any(item not in "0123456789abcdef" for item in fingerprint):
            raise OnlyResearchDatasetNotFoundError("DATASET_SNAPSHOT_NOT_FOUND")
        return self._root / "sha256" / fingerprint[:2] / fingerprint

    def _materialization_target(self, materialization_id: str) -> Path:
        prefix = "dataset-materialization:"
        fingerprint = materialization_id.removeprefix(prefix)
        if (
            not materialization_id.startswith(prefix)
            or len(fingerprint) != 64
            or any(item not in "0123456789abcdef" for item in fingerprint)
        ):
            raise OnlyResearchDatasetNotFoundError("DATASET_MATERIALIZATION_NOT_FOUND")
        return self._root / "materializations" / "sha256" / fingerprint[:2] / f"{fingerprint}.json"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_descriptor(descriptor: int, limit: int | None) -> bytes:
    with os.fdopen(os.dup(descriptor), "rb") as stream:
        stream.seek(0)
        return stream.read() if limit is None else stream.read(limit + 1)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
