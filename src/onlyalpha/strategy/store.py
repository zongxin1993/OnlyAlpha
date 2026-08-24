"""Verified atomic immutable Strategy Revision semantic store."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path

from onlyalpha.canonical import only_canonical_json
from onlyalpha.strategy.errors import OnlyStrategyStoreError
from onlyalpha.strategy.revision import OnlyStrategyFingerprint, OnlyStrategyRevision


class OnlyStrategyRevisionStore:
    """Sole semantic authority for immutable Strategy Revision content."""

    def __init__(self, semantic_root: Path) -> None:
        self._root = semantic_root / "strategy" / "revisions"

    def exists(self, strategy_fingerprint: OnlyStrategyFingerprint | str) -> bool:
        return self._target(_fingerprint(strategy_fingerprint)).is_dir()

    def commit(self, revision: OnlyStrategyRevision) -> OnlyStrategyRevision:
        if not isinstance(revision, OnlyStrategyRevision):
            raise OnlyStrategyStoreError("STRATEGY_INVALID", "commit requires a Strategy Revision")
        fingerprint = str(revision.strategy_fingerprint)
        target = self._target(fingerprint)
        if target.exists() or target.is_symlink():
            return self._resolve_existing(revision)
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = target.parent / f".stage-{uuid.uuid4().hex}"
        try:
            stage.mkdir()
            manifest = {
                "schema_version": 1,
                "strategy_fingerprint": fingerprint,
                "revision": revision.to_dict(),
            }
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
                return self._resolve_existing(revision)
            parent = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
            return self.load_verified(fingerprint)
        except OnlyStrategyStoreError:
            raise
        except Exception as exc:
            raise OnlyStrategyStoreError("STRATEGY_COMMIT_FAILED", "atomic publication failed") from exc
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def load_verified(self, strategy_fingerprint: OnlyStrategyFingerprint | str) -> OnlyStrategyRevision:
        fingerprint = _fingerprint(strategy_fingerprint)
        return self._read_verified(self._target(fingerprint), fingerprint)

    def _resolve_existing(self, candidate: OnlyStrategyRevision) -> OnlyStrategyRevision:
        fingerprint = str(candidate.strategy_fingerprint)
        existing = self.load_verified(fingerprint)
        if existing.to_dict() != candidate.to_dict():
            raise OnlyStrategyStoreError("DETERMINISTIC_STRATEGY_CONFLICT", fingerprint)
        return existing

    def _read_verified(self, root: Path, expected_fingerprint: str) -> OnlyStrategyRevision:
        if not root.is_dir():
            raise OnlyStrategyStoreError("STRATEGY_NOT_FOUND", expected_fingerprint)
        try:
            manifest_path = root / "manifest.json"
            if root.is_symlink() or manifest_path.is_symlink():
                raise ValueError("Strategy authority may not contain symlinks")
            if {item.name for item in root.iterdir()} != {"manifest.json"} or not manifest_path.is_file():
                raise ValueError("unexpected Strategy Revision entries")
            raw = manifest_path.read_text(encoding="utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, dict) or set(payload) != {"schema_version", "strategy_fingerprint", "revision"}:
                raise ValueError("Strategy manifest fields are invalid")
            if payload["schema_version"] != 1 or payload["strategy_fingerprint"] != expected_fingerprint:
                raise ValueError("Strategy manifest path identity mismatch")
            revision_payload = payload["revision"]
            if not isinstance(revision_payload, dict):
                raise ValueError("Strategy Revision must be an object")
            revision = OnlyStrategyRevision.from_dict(revision_payload)
            if str(revision.strategy_fingerprint) != expected_fingerprint:
                raise ValueError("Strategy Revision identity mismatch")
            if raw != only_canonical_json(payload):
                raise ValueError("Strategy manifest is not canonical JSON")
            return revision
        except OnlyStrategyStoreError:
            raise
        except Exception as exc:
            raise OnlyStrategyStoreError("STRATEGY_CORRUPT", expected_fingerprint) from exc

    def _target(self, fingerprint: str) -> Path:
        return self._root / "sha256" / fingerprint[:2] / fingerprint


def _fingerprint(value: OnlyStrategyFingerprint | str) -> str:
    try:
        return str(value if isinstance(value, OnlyStrategyFingerprint) else OnlyStrategyFingerprint(value))
    except (TypeError, ValueError) as exc:
        raise OnlyStrategyStoreError("STRATEGY_NOT_FOUND", "invalid Strategy fingerprint") from exc


__all__ = ["OnlyStrategyRevisionStore"]
