"""Atomic immutable persistence and self-contained verification for Research Artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from onlyalpha.research.evaluation.result import OnlyResearchStatisticStatus

from .errors import OnlyResearchArtifactStoreError
from .identity import RESEARCH_ARTIFACT_PROFILE, only_research_artifact_content_fingerprint
from .materializer import OnlyResearchArtifactCandidate
from .model import (
    RESEARCH_ARTIFACT_STATISTICS_SCHEMA,
    OnlyResearchArtifact,
    OnlyResearchArtifactDisposition,
    OnlyResearchArtifactManifest,
    OnlyResearchArtifactOutcome,
    OnlyResearchArtifactStatisticsRow,
    OnlyResearchArtifactStatisticsTable,
)
from .verification import verify_statistics_groups as _verify_groups

_SCHEMA = pa.schema(
    (
        pa.field("statistics_fingerprint", pa.string(), nullable=False),
        pa.field("ts_event_ns", pa.int64(), nullable=False),
        pa.field("statistic_value", pa.decimal128(38, 12), nullable=True),
        pa.field("sample_count", pa.int64(), nullable=False),
        pa.field("status", pa.string(), nullable=False),
    )
)


class OnlyParquetResearchArtifactStore:
    def __init__(
        self,
        root: Path,
        *,
        compression: str = "zstd",
        row_group_size: int | None = None,
        audit_time: Callable[[], datetime] | None = None,
    ) -> None:
        self._root = root
        self._compression = compression
        self._row_group_size = row_group_size
        self._audit_time = audit_time

    def exists(self, research_result_fingerprint: str) -> bool:
        return self._target(research_result_fingerprint).exists()

    def commit(self, candidate: OnlyResearchArtifactCandidate) -> OnlyResearchArtifactOutcome:
        admitted, table = self._admit(candidate)
        target = self._target(admitted.research_result_fingerprint)
        if target.exists():
            existing = self._resolve_existing(admitted)
            return self._outcome(OnlyResearchArtifactDisposition.REUSED, existing)
        created_at = self._audit_timestamp()
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = target.parent / f".stage-{uuid.uuid4().hex}"
        stage.mkdir()
        try:
            data_path = stage / "statistics.parquet"
            pq.write_table(table, data_path, compression=self._compression, row_group_size=self._row_group_size)
            restored = pq.read_table(data_path)
            if restored.schema != table.schema or not restored.equals(table, check_metadata=True):
                raise OnlyResearchArtifactStoreError("ARTIFACT_COMMIT_FAILED", "Parquet logical round-trip mismatch")
            manifest = OnlyResearchArtifactManifest(
                admitted.research_result_plan_fingerprint,
                admitted.research_result_content_fingerprint,
                admitted.research_result_fingerprint,
                admitted.dataset_snapshot_fingerprint,
                admitted.statistics_results,
                OnlyResearchArtifactStatisticsTable(len(admitted.rows), _sha(data_path)),
                admitted.artifact_content_fingerprint,
                created_at,
            )
            (stage / "artifact_manifest.json").write_text(
                json.dumps(manifest.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            try:
                self._read_verified(stage, admitted.research_result_fingerprint)
            except OnlyResearchArtifactStoreError as exc:
                raise OnlyResearchArtifactStoreError(
                    "ARTIFACT_COMMIT_FAILED", "staged Research Artifact verification failed"
                ) from exc
            try:
                os.rename(stage, target)
            except OSError:
                if not target.exists():
                    raise
                existing = self._resolve_existing(admitted)
                return self._outcome(OnlyResearchArtifactDisposition.REUSED, existing)
            committed = self.load_verified(admitted.research_result_fingerprint)
            return self._outcome(OnlyResearchArtifactDisposition.EXECUTED, committed)
        except OnlyResearchArtifactStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchArtifactStoreError("ARTIFACT_COMMIT_FAILED", "atomic publication failed") from exc
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def load_verified(self, research_result_fingerprint: str) -> OnlyResearchArtifact:
        return self._read_verified(self._target(research_result_fingerprint), research_result_fingerprint)

    def _admit(self, candidate: OnlyResearchArtifactCandidate) -> tuple[OnlyResearchArtifactCandidate, pa.Table]:
        if not isinstance(candidate, OnlyResearchArtifactCandidate):
            raise OnlyResearchArtifactStoreError("ARTIFACT_INVALID", "candidate contract is invalid")
        try:
            if candidate.statistics_results != tuple(sorted(candidate.statistics_results)):
                raise ValueError("Statistics catalog is not canonical")
            if candidate.rows != tuple(sorted(candidate.rows)):
                raise ValueError("Statistics rows are not canonical")
            if sum(item.row_count for item in candidate.statistics_results) != len(candidate.rows):
                raise ValueError("Statistics catalog row count mismatch")
            expected = only_research_artifact_content_fingerprint(
                candidate.research_result_fingerprint,
                candidate.dataset_snapshot_fingerprint,
                tuple(item.to_dict() for item in candidate.statistics_results),
            )
            if expected != candidate.artifact_content_fingerprint:
                raise ValueError("Artifact content fingerprint mismatch")
            table = _table(candidate.rows)
            _verify_groups(candidate.statistics_results, candidate.rows)
            return candidate, table
        except OnlyResearchArtifactStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchArtifactStoreError("ARTIFACT_INVALID", str(exc)) from exc

    def _resolve_existing(self, candidate: OnlyResearchArtifactCandidate) -> OnlyResearchArtifact:
        existing = self.load_verified(candidate.research_result_fingerprint)
        if existing.manifest.artifact_content_fingerprint != candidate.artifact_content_fingerprint:
            raise OnlyResearchArtifactStoreError(
                "DETERMINISTIC_ARTIFACT_CONFLICT", candidate.research_result_fingerprint
            )
        return existing

    def _read_verified(self, root: Path, expected_research_result_fingerprint: str) -> OnlyResearchArtifact:
        if root.is_symlink():
            raise OnlyResearchArtifactStoreError("ARTIFACT_CORRUPT", "Artifact target may not be a symlink")
        if not root.is_dir():
            raise OnlyResearchArtifactStoreError("ARTIFACT_NOT_FOUND", expected_research_result_fingerprint)
        try:
            manifest_path = root / "artifact_manifest.json"
            data_path = root / "statistics.parquet"
            if manifest_path.is_symlink() or data_path.is_symlink():
                raise ValueError("Research Artifact may not contain symlinks")
            entries = tuple(root.iterdir())
            if {item.name for item in entries} != {"artifact_manifest.json", "statistics.parquet"}:
                raise ValueError("unexpected Research Artifact files")
            if any(not item.is_file() for item in entries):
                raise ValueError("Research Artifact contains a non-file entry")
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Research Artifact manifest must be an object")
            manifest = OnlyResearchArtifactManifest.from_dict(payload)
            if manifest.research_result_fingerprint != expected_research_result_fingerprint:
                raise ValueError("Research Artifact path identity mismatch")
            if _sha(data_path) != manifest.statistics_table.data_byte_sha256:
                raise ValueError("Research Artifact data byte hash mismatch")
            table = pq.read_table(data_path)
            if table.schema != _SCHEMA or _schema_payload(table.schema) != manifest.statistics_table.arrow_schema:
                raise ValueError("Research Artifact Arrow schema mismatch")
            rows = _rows(table)
            if len(rows) != manifest.statistics_table.row_count:
                raise ValueError("Research Artifact row count mismatch")
            _verify_groups(manifest.statistics_results, rows)
            artifact = only_research_artifact_content_fingerprint(
                manifest.research_result_fingerprint,
                manifest.dataset_snapshot_fingerprint,
                tuple(item.to_dict() for item in manifest.statistics_results),
            )
            if artifact != manifest.artifact_content_fingerprint:
                raise ValueError("Research Artifact content identity mismatch")
            return OnlyResearchArtifact(manifest, rows, table)
        except OnlyResearchArtifactStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchArtifactStoreError("ARTIFACT_CORRUPT", str(exc)) from exc

    def _target(self, fingerprint: str) -> Path:
        if not _valid_sha(fingerprint):
            raise OnlyResearchArtifactStoreError("ARTIFACT_NOT_FOUND", "invalid Research Result fingerprint")
        return (
            self._root / RESEARCH_ARTIFACT_PROFILE.lower().replace("_", "-") / "sha256" / fingerprint[:2] / fingerprint
        )

    def _audit_timestamp(self) -> datetime:
        if self._audit_time is None:
            raise OnlyResearchArtifactStoreError("ARTIFACT_INVALID", "audit time authority is required for commit")
        value = self._audit_time()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise OnlyResearchArtifactStoreError("ARTIFACT_INVALID", "audit time must be timezone-aware UTC")
        return value

    @staticmethod
    def _outcome(
        disposition: OnlyResearchArtifactDisposition, artifact: OnlyResearchArtifact
    ) -> OnlyResearchArtifactOutcome:
        return OnlyResearchArtifactOutcome(
            disposition,
            artifact.manifest.research_result_fingerprint,
            artifact.manifest.artifact_content_fingerprint,
        )


def _table(rows: tuple[OnlyResearchArtifactStatisticsRow, ...]) -> pa.Table:
    return pa.Table.from_arrays(
        (
            pa.array((row.statistics_fingerprint for row in rows), type=pa.string()),
            pa.array((row.ts_event_ns for row in rows), type=pa.int64()),
            pa.array((row.statistic_value for row in rows), type=pa.decimal128(38, 12)),
            pa.array((row.sample_count for row in rows), type=pa.int64()),
            pa.array((row.status.value for row in rows), type=pa.string()),
        ),
        schema=_SCHEMA,
    )


def _rows(table: pa.Table) -> tuple[OnlyResearchArtifactStatisticsRow, ...]:
    try:
        rows = tuple(
            OnlyResearchArtifactStatisticsRow(
                item["statistics_fingerprint"],
                item["ts_event_ns"],
                item["statistic_value"],
                item["sample_count"],
                OnlyResearchStatisticStatus(item["status"]),
            )
            for item in table.to_pylist()
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Research Artifact logical row is invalid") from exc
    if rows != tuple(sorted(rows)) or len({(row.statistics_fingerprint, row.ts_event_ns) for row in rows}) != len(rows):
        raise ValueError("Research Artifact rows are not canonical")
    return rows


def _schema_payload(schema: pa.Schema) -> tuple[dict[str, object], ...]:
    result: list[dict[str, object]] = []
    for field in schema:
        if pa.types.is_decimal(field.type):
            data_type: dict[str, object] = {
                "kind": "DECIMAL",
                "bit_width": field.type.bit_width,
                "precision": field.type.precision,
                "scale": field.type.scale,
            }
        elif pa.types.is_integer(field.type):
            data_type = {"kind": "INTEGER", "bit_width": field.type.bit_width, "signed": True}
        elif pa.types.is_string(field.type):
            data_type = {"kind": "STRING"}
        else:
            raise ValueError("Research Artifact Arrow type is unsupported")
        result.append({"name": field.name, "data_type": data_type, "nullable": field.nullable})
    payload = tuple(result)
    if payload != RESEARCH_ARTIFACT_STATISTICS_SCHEMA:
        raise ValueError("Research Artifact Arrow schema is unsupported")
    return payload


def _valid_sha(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(item in "0123456789abcdef" for item in value)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
