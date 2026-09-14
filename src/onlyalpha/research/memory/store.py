"""Disposable immutable revisions; atomic pointer is operational, never source truth."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path

from onlyalpha.canonical import only_canonical_json

from .projector import (
    PROJECTION_SCHEMA_VERSION,
    PROJECTOR_ALGORITHM_VERSION,
    OnlyExperimentMemoryProjectionV1,
    OnlyMemoryCutReader,
    OnlyMemoryProjectionRecordV1,
    OnlyMemorySourceRefV1,
    only_build_experiment_memory_projection,
)
from .source_manifest import OnlyExperimentMemorySourceCutManifestV1, OnlyMemoryProjectionError


def _sha(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)


class OnlyExperimentMemoryRevisionStore:
    """Only the supplied dedicated projection root may be removed to rebuild."""

    def __init__(self, root: Path) -> None:
        if root.name != "experiment-memory":
            raise OnlyMemoryProjectionError("PROJECTION_ROOT_INVALID")
        self._root = root

    def _safe(self, path: Path) -> None:
        if not path.is_relative_to(self._root):
            raise OnlyMemoryProjectionError("PROJECTION_CORRUPT")
        for part in (self._root, *list(path.parents)[:-1], path):
            if part.is_symlink():
                raise OnlyMemoryProjectionError("PROJECTION_CORRUPT")

    def _target(self, fingerprint: str) -> Path:
        if not _sha(fingerprint):
            raise OnlyMemoryProjectionError("PROJECTION_CORRUPT")
        return self._root / "revisions" / "sha256" / fingerprint[:2] / fingerprint

    def load_verified(self, fingerprint: str) -> OnlyExperimentMemoryProjectionV1:
        target = self._target(fingerprint)
        self._safe(target)
        try:
            projection_path = target / "projection.json"
            if (
                not target.is_dir()
                or {p.name for p in target.iterdir()} != {"projection.json"}
                or projection_path.is_symlink()
            ):
                raise ValueError("incomplete revision")
            raw = projection_path.read_text(encoding="utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, dict) or raw != only_canonical_json(payload):
                raise ValueError("noncanonical revision")
            if (
                set(payload)
                != {
                    "projection_schema_version",
                    "projector_algorithm_version",
                    "source_manifest",
                    "records",
                    "logical_digest",
                    "revision_fingerprint",
                }
                or payload["projection_schema_version"] != PROJECTION_SCHEMA_VERSION
                or payload["projector_algorithm_version"] != PROJECTOR_ALGORITHM_VERSION
            ):
                raise ValueError("unsupported revision")
            source_manifest = OnlyExperimentMemorySourceCutManifestV1.from_dict(payload["source_manifest"])
            if not isinstance(payload["records"], list):
                raise ValueError("records")
            records: list[OnlyMemoryProjectionRecordV1] = []
            for row in payload["records"]:
                if not isinstance(row, dict) or set(row) != {"kind", "facets", "source_refs"}:
                    raise ValueError("record")
                refs = tuple(OnlyMemorySourceRefV1(**ref) for ref in row["source_refs"])
                records.append(OnlyMemoryProjectionRecordV1(row["kind"], row["facets"], refs))
            if records != sorted(records, key=lambda r: only_canonical_json(r.to_dict())):
                raise ValueError("record order")
            cuts = {cut.source_family: cut.cut_fingerprint for cut in source_manifest.cuts}
            if any(
                ref.cut_fingerprint != cuts.get(ref.source_family) for record in records for ref in record.source_refs
            ):
                raise ValueError("source cut reference")
            projection = OnlyExperimentMemoryProjectionV1(source_manifest, tuple(records))
            if (
                projection.logical_digest != payload["logical_digest"]
                or projection.revision_fingerprint != fingerprint
                or fingerprint != payload["revision_fingerprint"]
            ):
                raise ValueError("revision identity")
            return projection
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise OnlyMemoryProjectionError("PROJECTION_CORRUPT") from exc

    def publish_and_activate(
        self,
        source_manifest: OnlyExperimentMemorySourceCutManifestV1,
        readers: Mapping[str, OnlyMemoryCutReader],
        verify_exact_reference: Callable[[str, str], Mapping[str, object] | None],
        *,
        before_activation: Callable[[], None] | None = None,
    ) -> str:
        """Full owner-verified build, separate publication, verified read, atomic switch."""
        projection = only_build_experiment_memory_projection(source_manifest, readers, verify_exact_reference)
        return self._publish_and_activate(projection, before_activation=before_activation)

    def _publish_and_activate(
        self, projection: OnlyExperimentMemoryProjectionV1, *, before_activation: Callable[[], None] | None = None
    ) -> str:
        fingerprint = projection.revision_fingerprint
        target = self._target(fingerprint)
        self._safe(target)
        self._safe(self._root / "active")
        self._root.mkdir(parents=True, exist_ok=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = target.parent / f".stage-{uuid.uuid4().hex}"
        self._safe(stage)
        try:
            if not target.exists():
                stage.mkdir(mode=0o700)
                with (stage / "projection.json").open("x", encoding="utf-8") as stream:
                    stream.write(only_canonical_json(projection.to_dict()))
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.rename(stage, target)
                except OSError:
                    if not target.exists():
                        raise
                self._fsync_dir(target.parent)
            if self.load_verified(fingerprint) != projection:
                raise OnlyMemoryProjectionError("PROJECTION_SOURCE_CONFLICT")
            if before_activation is not None:
                before_activation()
            active = self._root / "active"
            active.mkdir(exist_ok=True)
            pointer = active / "current"
            self._safe(pointer)
            temporary = active / f".stage-{uuid.uuid4().hex}"
            with temporary.open("x", encoding="ascii") as stream:
                stream.write(fingerprint)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, pointer)
            self._fsync_dir(active)
            return fingerprint
        except OnlyMemoryProjectionError:
            raise
        except Exception as exc:
            raise OnlyMemoryProjectionError("PROJECTION_ACTIVATION_FAILED") from exc
        finally:
            if stage.exists():
                shutil.rmtree(stage)

    def load_active_verified(self) -> OnlyExperimentMemoryProjectionV1:
        pointer = self._root / "active" / "current"
        self._safe(pointer)
        try:
            fingerprint = pointer.read_text(encoding="ascii")
        except OSError as exc:
            raise OnlyMemoryProjectionError("PROJECTION_CORRUPT") from exc
        return self.load_verified(fingerprint)

    @staticmethod
    def _fsync_dir(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
