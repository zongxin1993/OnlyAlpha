"""Content-addressed Product Backtest Evidence manifest."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json


@dataclass(frozen=True, slots=True)
class OnlyBacktestEvidenceManifest:
    backtest_run_id: str
    specification_fingerprint: str
    admission_resolution_fingerprint: str
    strategy_fingerprint: str
    dataset_binding_fingerprint: str
    market_product_composition_fingerprint: str
    kernel_semantics_version: str
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
            "market_product_composition_fingerprint",
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
            if not name or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("BACKTEST_EVIDENCE_ARTIFACT_INVALID")
            if size < 0 or not media_type:
                raise ValueError("BACKTEST_EVIDENCE_ARTIFACT_INVALID")

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
            "market_product_composition_fingerprint": self.market_product_composition_fingerprint,
            "kernel_semantics_version": self.kernel_semantics_version,
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
                path.write_bytes(artifacts[name])
            (stage / "manifest.json").write_text(only_canonical_json(manifest.to_dict()), encoding="utf-8")
            self._read_verified(stage, manifest.evidence_fingerprint)
            os.rename(stage, target)
            return self.load_verified(manifest.evidence_fingerprint)
        finally:
            if stage.exists():
                shutil.rmtree(stage)

    def load_verified(self, fingerprint: str) -> OnlyBacktestEvidenceManifest:
        return self._read_verified(self._target(fingerprint), fingerprint)

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
                "market_product_composition_fingerprint",
                "kernel_semantics_version",
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
                market_product_composition_fingerprint=str(payload["market_product_composition_fingerprint"]),
                kernel_semantics_version=str(payload["kernel_semantics_version"]),
                result_fingerprint=str(payload["result_fingerprint"]),
                determinism_fingerprint=str(payload["determinism_fingerprint"]),
                artifacts=artifacts,
                schema_version=int(payload["schema_version"]),
            )
            if manifest.evidence_fingerprint != fingerprint:
                raise ValueError("manifest fingerprint differs")
            for name, digest, size, _ in manifest.artifacts:
                data = (root / name).read_bytes()
                import hashlib

                if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
                    raise ValueError("artifact content differs")
            return manifest
        except Exception as exc:
            raise ValueError("BACKTEST_EVIDENCE_CORRUPT") from exc

    def _target(self, fingerprint: str) -> Path:
        if len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
            raise ValueError("BACKTEST_EVIDENCE_ID_INVALID")
        return self._root / fingerprint[:2] / fingerprint


__all__ = ["OnlyBacktestEvidenceManifest", "OnlyBacktestEvidenceStore"]
