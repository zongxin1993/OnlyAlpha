"""Local content-addressed implementation of the exact Artifact Store port."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from onlyalpha.canonical import only_canonical_json
from onlyalpha.distribution import OnlyDistributionArtifactManifest


@dataclass(frozen=True, slots=True)
class OnlyLocalImmutableArtifactStore:
    root: Path

    def put_once(self, manifest: OnlyDistributionArtifactManifest, artifact_bytes: bytes) -> Path:
        self._verify_bytes(manifest, artifact_bytes)
        artifact_path, manifest_path = self._paths(manifest.artifact_sha256)
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_once(artifact_path, artifact_bytes, "RUNTIME_GENERATION_ARTIFACT_CONFLICT")
        encoded = (only_canonical_json(manifest.to_dict()) + "\n").encode()
        try:
            self._write_once(manifest_path, encoded, "RUNTIME_GENERATION_ARTIFACT_MANIFEST_CONFLICT")
        except Exception:
            if artifact_path.read_bytes() != artifact_bytes:
                raise
            raise
        self.verify_exact(manifest)
        return artifact_path

    def fetch_exact(self, artifact_sha256: str) -> tuple[OnlyDistributionArtifactManifest, bytes]:
        artifact_path, manifest_path = self._paths(artifact_sha256)
        try:
            raw_manifest: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(raw_manifest, dict):
                raise ValueError("RUNTIME_GENERATION_ARTIFACT_MANIFEST_MISMATCH")
            manifest = OnlyDistributionArtifactManifest.from_dict(cast(dict[str, object], raw_manifest))
            artifact_bytes = artifact_path.read_bytes()
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError("RUNTIME_GENERATION_ARTIFACT_MISMATCH") from exc
        if manifest.artifact_sha256 != artifact_sha256:
            raise ValueError("RUNTIME_GENERATION_ARTIFACT_MISMATCH")
        self._verify_bytes(manifest, artifact_bytes)
        return manifest, artifact_bytes

    def verify_exact(self, expected: OnlyDistributionArtifactManifest) -> Path:
        actual, artifact_bytes = self.fetch_exact(expected.artifact_sha256)
        if actual != expected:
            raise ValueError("RUNTIME_GENERATION_ARTIFACT_MANIFEST_MISMATCH")
        self._verify_bytes(expected, artifact_bytes)
        return self._paths(expected.artifact_sha256)[0]

    def manifests(self) -> tuple[OnlyDistributionArtifactManifest, ...]:
        if not self.root.exists():
            return ()
        result = []
        for path in sorted(self.root.glob("*/*/manifest.json")):
            try:
                payload: Any = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError
                manifest = OnlyDistributionArtifactManifest.from_dict(cast(dict[str, object], payload))
                self.verify_exact(manifest)
                result.append(manifest)
            except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ValueError("RUNTIME_GENERATION_ARTIFACT_MISMATCH") from exc
        return tuple(result)

    def _paths(self, artifact_sha256: str) -> tuple[Path, Path]:
        if len(artifact_sha256) != 64 or any(char not in "0123456789abcdef" for char in artifact_sha256):
            raise ValueError("RUNTIME_GENERATION_ARTIFACT_MISMATCH")
        directory = self.root / artifact_sha256[:2] / artifact_sha256
        return directory / "artifact.whl", directory / "manifest.json"

    @staticmethod
    def _verify_bytes(manifest: OnlyDistributionArtifactManifest, content: bytes) -> None:
        import hashlib

        if len(content) != manifest.artifact_size or hashlib.sha256(content).hexdigest() != manifest.artifact_sha256:
            raise ValueError("RUNTIME_GENERATION_ARTIFACT_MISMATCH")

    @staticmethod
    def _write_once(path: Path, content: bytes, conflict_code: str) -> None:
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if path.read_bytes() != content:
                raise ValueError(conflict_code) from None
            return
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except Exception:
            raise
