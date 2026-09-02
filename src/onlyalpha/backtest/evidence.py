"""Content-addressed Product Backtest Evidence manifest."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json


@dataclass(frozen=True, slots=True)
class OnlyBacktestEvidenceManifest:
    backtest_run_id: str
    specification_fingerprint: str
    admission_resolution_fingerprint: str
    strategy_fingerprint: str
    dataset_binding_fingerprint: str
    base_dataset_snapshot_fingerprint: str
    market_product_composition_fingerprint: str
    portfolio_profile_fingerprint: str
    risk_profile_fingerprint: str
    execution_profile_fingerprint: str
    kernel_semantics_version: str
    implementation_fingerprints: tuple[str, ...]
    result_fingerprint: str
    determinism_fingerprint: str
    artifacts: tuple[tuple[str, str, int, str], ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not self.backtest_run_id or not self.kernel_semantics_version.strip():
            raise ValueError("BACKTEST_EVIDENCE_MANIFEST_INVALID")
        for name in (
            "specification_fingerprint",
            "admission_resolution_fingerprint",
            "strategy_fingerprint",
            "dataset_binding_fingerprint",
            "base_dataset_snapshot_fingerprint",
            "market_product_composition_fingerprint",
            "portfolio_profile_fingerprint",
            "risk_profile_fingerprint",
            "execution_profile_fingerprint",
            "result_fingerprint",
            "determinism_fingerprint",
        ):
            value = getattr(self, name)
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError(f"{name} must be a lower-case SHA256")
        names = tuple(item[0] for item in self.artifacts)
        if names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise ValueError("BACKTEST_EVIDENCE_ARTIFACTS_INVALID")
        for name, digest, size, media_type in self.artifacts:
            _artifact_name(name)
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("BACKTEST_EVIDENCE_ARTIFACT_INVALID")
            if size < 0 or not media_type:
                raise ValueError("BACKTEST_EVIDENCE_ARTIFACT_INVALID")
        if self.implementation_fingerprints != tuple(sorted(set(self.implementation_fingerprints))) or any(
            len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
            for value in self.implementation_fingerprints
        ):
            raise ValueError("BACKTEST_EVIDENCE_IMPLEMENTATIONS_INVALID")

    @property
    def evidence_fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict(include_fingerprint=False))

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "backtest_run_id": self.backtest_run_id,
            "specification_fingerprint": self.specification_fingerprint,
            "admission_resolution_fingerprint": self.admission_resolution_fingerprint,
            "strategy_fingerprint": self.strategy_fingerprint,
            "dataset_binding_fingerprint": self.dataset_binding_fingerprint,
            "base_dataset_snapshot_fingerprint": self.base_dataset_snapshot_fingerprint,
            "market_product_composition_fingerprint": self.market_product_composition_fingerprint,
            "portfolio_profile_fingerprint": self.portfolio_profile_fingerprint,
            "risk_profile_fingerprint": self.risk_profile_fingerprint,
            "execution_profile_fingerprint": self.execution_profile_fingerprint,
            "kernel_semantics_version": self.kernel_semantics_version,
            "implementation_fingerprints": list(self.implementation_fingerprints),
            "result_fingerprint": self.result_fingerprint,
            "determinism_fingerprint": self.determinism_fingerprint,
            "artifacts": [
                {"name": name, "sha256": digest, "size": size, "media_type": media_type}
                for name, digest, size, media_type in self.artifacts
            ],
        }
        if include_fingerprint:
            payload["evidence_fingerprint"] = self.evidence_fingerprint
        return payload


class OnlyBacktestEvidenceStore:
    def __init__(self, root: Path) -> None:
        self._root = root / "backtest" / "evidence" / "sha256"

    def publish(
        self, manifest: OnlyBacktestEvidenceManifest, artifacts: dict[str, bytes]
    ) -> OnlyBacktestEvidenceManifest:
        if set(artifacts) != {item[0] for item in manifest.artifacts}:
            raise ValueError("BACKTEST_EVIDENCE_ARTIFACT_SET_MISMATCH")
        target = self._target(manifest.evidence_fingerprint)
        if target.exists() or target.is_symlink():
            existing = self.load_verified(manifest.evidence_fingerprint)
            if existing != manifest:
                raise ValueError("BACKTEST_EVIDENCE_CORRUPT")
            return existing
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = target.parent / f".stage-{uuid.uuid4().hex}"
        try:
            stage.mkdir()
            for name, _, _, _ in manifest.artifacts:
                path = stage / name
                path.parent.mkdir(parents=True, exist_ok=True)
                data = artifacts[name]
                expected = next(item for item in manifest.artifacts if item[0] == name)
                if len(data) != expected[2] or sha256(data).hexdigest() != expected[1]:
                    raise ValueError("BACKTEST_EVIDENCE_ARTIFACT_CONTENT_MISMATCH")
                _write_exclusive(path, data)
            _write_exclusive(
                stage / "manifest.json",
                only_canonical_json(manifest.to_dict()).encode("utf-8"),
            )
            self._read_verified(stage, manifest.evidence_fingerprint)
            _fsync_tree_directories(stage)
            try:
                os.rename(stage, target)
            except OSError:
                if not target.exists():
                    raise
            _fsync_directory(target.parent)
            return self.load_verified(manifest.evidence_fingerprint)
        finally:
            if stage.exists():
                shutil.rmtree(stage)

    def load_verified(self, fingerprint: str) -> OnlyBacktestEvidenceManifest:
        return self._read_verified(self._target(fingerprint), fingerprint)

    def find_for_run(self, backtest_run_id: str) -> OnlyBacktestEvidenceManifest | None:
        matches: list[OnlyBacktestEvidenceManifest] = []
        if not self._root.exists():
            return None
        for candidate in sorted(self._root.glob("[0-9a-f][0-9a-f]/[0-9a-f]" + "[0-9a-f]" * 63)):
            manifest = self.load_verified(candidate.name)
            if manifest.backtest_run_id == backtest_run_id:
                matches.append(manifest)
        if len(matches) > 1:
            raise ValueError("BACKTEST_EVIDENCE_RUN_CONFLICT")
        return None if not matches else matches[0]

    def read_artifact(self, fingerprint: str, name: str) -> tuple[bytes, str]:
        _artifact_name(name)
        manifest = self.load_verified(fingerprint)
        matches = tuple(item for item in manifest.artifacts if item[0] == name)
        if len(matches) != 1:
            raise ValueError("BACKTEST_EVIDENCE_ARTIFACT_NOT_FOUND")
        path = self._target(fingerprint) / name
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != self._root.parent):
            raise ValueError("BACKTEST_EVIDENCE_CORRUPT")
        return path.read_bytes(), matches[0][3]

    def _read_verified(self, root: Path, fingerprint: str) -> OnlyBacktestEvidenceManifest:
        if not root.is_dir() or root.is_symlink():
            raise ValueError("BACKTEST_EVIDENCE_NOT_FOUND")
        try:
            manifest_path = root / "manifest.json"
            raw_manifest = manifest_path.read_text(encoding="utf-8")
            payload = json.loads(raw_manifest)
            if not isinstance(payload, dict) or payload.get("evidence_fingerprint") != fingerprint:
                raise ValueError("evidence identity differs")
            if raw_manifest != only_canonical_json(payload):
                raise ValueError("manifest is not canonical")
            payload = dict(payload)
            payload.pop("evidence_fingerprint")
            expected = {
                "schema_version",
                "backtest_run_id",
                "specification_fingerprint",
                "admission_resolution_fingerprint",
                "strategy_fingerprint",
                "dataset_binding_fingerprint",
                "base_dataset_snapshot_fingerprint",
                "market_product_composition_fingerprint",
                "portfolio_profile_fingerprint",
                "risk_profile_fingerprint",
                "execution_profile_fingerprint",
                "kernel_semantics_version",
                "implementation_fingerprints",
                "result_fingerprint",
                "determinism_fingerprint",
                "artifacts",
            }
            if set(payload) != expected:
                raise ValueError("manifest fields invalid")
            artifacts = tuple(
                (str(item["name"]), str(item["sha256"]), int(item["size"]), str(item["media_type"]))
                for item in payload["artifacts"]
            )
            manifest = OnlyBacktestEvidenceManifest(
                backtest_run_id=str(payload["backtest_run_id"]),
                specification_fingerprint=str(payload["specification_fingerprint"]),
                admission_resolution_fingerprint=str(payload["admission_resolution_fingerprint"]),
                strategy_fingerprint=str(payload["strategy_fingerprint"]),
                dataset_binding_fingerprint=str(payload["dataset_binding_fingerprint"]),
                base_dataset_snapshot_fingerprint=str(payload["base_dataset_snapshot_fingerprint"]),
                market_product_composition_fingerprint=str(payload["market_product_composition_fingerprint"]),
                portfolio_profile_fingerprint=str(payload["portfolio_profile_fingerprint"]),
                risk_profile_fingerprint=str(payload["risk_profile_fingerprint"]),
                execution_profile_fingerprint=str(payload["execution_profile_fingerprint"]),
                kernel_semantics_version=str(payload["kernel_semantics_version"]),
                implementation_fingerprints=tuple(str(item) for item in payload["implementation_fingerprints"]),
                result_fingerprint=str(payload["result_fingerprint"]),
                determinism_fingerprint=str(payload["determinism_fingerprint"]),
                artifacts=artifacts,
                schema_version=int(payload["schema_version"]),
            )
            if manifest.evidence_fingerprint != fingerprint:
                raise ValueError("manifest fingerprint differs")
            expected_files = {"manifest.json", *(name for name, _, _, _ in manifest.artifacts)}
            actual_files = {
                item.relative_to(root).as_posix() for item in root.rglob("*") if item.is_file() or item.is_symlink()
            }
            if actual_files != expected_files:
                raise ValueError("unexpected Evidence entries")
            for name, digest, size, _ in manifest.artifacts:
                path = root / name
                if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != root.parent):
                    raise ValueError("artifact path traverses a symlink")
                data = path.read_bytes()
                if len(data) != size or sha256(data).hexdigest() != digest:
                    raise ValueError("artifact content differs")
            return manifest
        except Exception as exc:
            raise ValueError("BACKTEST_EVIDENCE_CORRUPT") from exc

    def _target(self, fingerprint: str) -> Path:
        if len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
            raise ValueError("BACKTEST_EVIDENCE_ID_INVALID")
        return self._root / fingerprint[:2] / fingerprint


def _artifact_name(value: str) -> None:
    if not value or value in {".", ".."} or "\\" in value:
        raise ValueError("BACKTEST_EVIDENCE_ARTIFACT_PATH_INVALID")
    path = PurePosixPath(value)
    if path.is_absolute() or value != path.as_posix() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("BACKTEST_EVIDENCE_ARTIFACT_PATH_INVALID")
    if path.name == "manifest.json":
        raise ValueError("BACKTEST_EVIDENCE_ARTIFACT_PATH_INVALID")


def _write_exclusive(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_tree_directories(root: Path) -> None:
    directories = sorted(
        (item for item in root.rglob("*") if item.is_dir()), key=lambda item: len(item.parts), reverse=True
    )
    for directory in directories:
        _fsync_directory(directory)
    _fsync_directory(root)


__all__ = ["OnlyBacktestEvidenceManifest", "OnlyBacktestEvidenceStore"]
