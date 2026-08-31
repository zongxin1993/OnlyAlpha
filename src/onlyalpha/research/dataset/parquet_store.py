"""Atomic immutable content-addressed Parquet Dataset Snapshot store."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
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
from .schema import RESEARCH_BAR_DATASET_SCHEMA_V1


class OnlyResearchDatasetStoreError(RuntimeError):
    pass


class OnlyResearchDatasetNotFoundError(OnlyResearchDatasetStoreError):
    code = "DATASET_SNAPSHOT_NOT_FOUND"


class OnlyResearchDatasetCorruptError(OnlyResearchDatasetStoreError):
    code = "DATASET_SNAPSHOT_CORRUPT"


class OnlyParquetResearchDatasetSnapshotStore:
    def __init__(self, root: Path, *, compression: str = "zstd", row_group_size: int | None = None) -> None:
        self._root = root
        self._compression = compression
        self._row_group_size = row_group_size

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
            payload = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("manifest must be an object")
            return OnlyResearchDatasetSnapshot.from_dict(payload)
        except Exception as exc:
            raise OnlyResearchDatasetCorruptError("DATASET_SNAPSHOT_CORRUPT: manifest") from exc

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

    def _verify_root(self, root: Path, expected_fingerprint: str) -> OnlyResearchDatasetVerification:
        verification, _, _ = self._read_verified(root, expected_fingerprint)
        return verification

    def _read_verified(
        self, root: Path, expected_fingerprint: str
    ) -> tuple[OnlyResearchDatasetVerification, OnlyResearchDatasetSnapshot, pa.Table]:
        if not root.is_dir():
            raise OnlyResearchDatasetNotFoundError("DATASET_SNAPSHOT_NOT_FOUND")
        try:
            payload = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("manifest must be an object")
            snapshot = OnlyResearchDatasetSnapshot.from_dict(payload)
            if snapshot.snapshot_fingerprint != expected_fingerprint:
                raise ValueError("snapshot path identity mismatch")
            bars: list[OnlyBar] = []
            tables: list[pa.Table] = []
            total = 0
            for partition in snapshot.partitions:
                path = root / partition.relative_path
                if not path.is_file() or _sha(path) != partition.byte_sha256:
                    raise ValueError("partition byte hash mismatch")
                table = pq.read_table(path)
                restored = only_table_to_bars(table)
                if len(restored) != partition.row_count:
                    raise ValueError("partition row count mismatch")
                if only_content_fingerprint(restored) != partition.semantic_fingerprint:
                    raise ValueError("partition semantic fingerprint mismatch")
                total += len(restored)
                bars.extend(restored)
                tables.append(table)
            if total != snapshot.row_count or only_content_fingerprint(tuple(bars)) != snapshot.content_fingerprint:
                raise ValueError("global content mismatch")
            if (
                only_snapshot_fingerprint(
                    snapshot.definition, snapshot.dataset_schema, snapshot.content_fingerprint, snapshot.row_count
                )
                != snapshot.snapshot_fingerprint
            ):
                raise ValueError("snapshot semantic fingerprint mismatch")
            table = (
                pa.concat_tables(tables)
                if tables
                else pa.Table.from_pylist([], schema=RESEARCH_BAR_DATASET_SCHEMA_V1.arrow_schema)
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


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
