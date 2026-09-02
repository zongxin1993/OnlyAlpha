"""Immutable content-addressed Dataset economic-binding authority."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path

from onlyalpha.canonical import only_canonical_json

from .economic import OnlyResearchDatasetEconomicBinding


class OnlyDatasetEconomicBindingStoreError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


class OnlyDatasetEconomicBindingStore:
    def __init__(self, semantic_root: Path) -> None:
        self._root = semantic_root / "research" / "dataset-economic-bindings" / "sha256"

    def publish_verified(self, binding: OnlyResearchDatasetEconomicBinding) -> OnlyResearchDatasetEconomicBinding:
        fingerprint = binding.fingerprint
        target = self._target(fingerprint)
        if target.exists() or target.is_symlink():
            existing = self.load_verified(fingerprint)
            if existing != binding:
                raise OnlyDatasetEconomicBindingStoreError("DATASET_BINDING_CORRUPT", fingerprint)
            return existing
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = target.parent / f".stage-{uuid.uuid4().hex}"
        try:
            stage.mkdir()
            manifest = {"binding": binding.semantic_payload(), "binding_fingerprint": fingerprint}
            path = stage / "manifest.json"
            with path.open("x", encoding="utf-8") as stream:
                stream.write(only_canonical_json(manifest))
                stream.flush()
                os.fsync(stream.fileno())
            self._read_verified(stage, fingerprint)
            directory = os.open(stage, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            try:
                os.rename(stage, target)
            except OSError:
                if not target.exists():
                    raise
            return self.load_verified(fingerprint)
        except OnlyDatasetEconomicBindingStoreError:
            raise
        except Exception as exc:
            raise OnlyDatasetEconomicBindingStoreError("DATASET_BINDING_PUBLISH_FAILED", fingerprint) from exc
        finally:
            if stage.exists():
                shutil.rmtree(stage)

    def load_verified(self, fingerprint: str) -> OnlyResearchDatasetEconomicBinding:
        _sha(fingerprint)
        return self._read_verified(self._target(fingerprint), fingerprint)

    def _read_verified(self, root: Path, fingerprint: str) -> OnlyResearchDatasetEconomicBinding:
        if not root.is_dir():
            raise OnlyDatasetEconomicBindingStoreError("DATASET_BINDING_NOT_FOUND", fingerprint)
        try:
            manifest = root / "manifest.json"
            if (
                root.is_symlink()
                or manifest.is_symlink()
                or {item.name for item in root.iterdir()} != {"manifest.json"}
            ):
                raise ValueError("unexpected Dataset binding entries")
            raw = manifest.read_text(encoding="utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, dict) or set(payload) != {"binding", "binding_fingerprint"}:
                raise ValueError("Dataset binding manifest fields are invalid")
            binding_payload = payload["binding"]
            if not isinstance(binding_payload, dict):
                raise ValueError("Dataset binding must be an object")
            binding = OnlyResearchDatasetEconomicBinding.from_dict(binding_payload)
            if payload["binding_fingerprint"] != fingerprint or binding.fingerprint != fingerprint:
                raise ValueError("Dataset binding identity differs")
            if raw != only_canonical_json(payload):
                raise ValueError("Dataset binding manifest is not canonical")
            return binding
        except OnlyDatasetEconomicBindingStoreError:
            raise
        except Exception as exc:
            raise OnlyDatasetEconomicBindingStoreError("DATASET_BINDING_CORRUPT", fingerprint) from exc

    def _target(self, fingerprint: str) -> Path:
        return self._root / fingerprint[:2] / fingerprint


def _sha(value: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise OnlyDatasetEconomicBindingStoreError("DATASET_BINDING_ID_INVALID", value)


__all__ = [name for name in globals() if name.startswith("Only")]
