"""Read-only Strategy capabilities and Freeze-sealed frozen publication authority."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from onlyalpha.canonical import only_canonical_json
from onlyalpha.strategy.errors import OnlyStrategyStoreError
from onlyalpha.strategy.freeze_relation import OnlyStrategyFreezeRelation
from onlyalpha.strategy.revision import OnlyStrategyFingerprint, OnlyStrategyRevision


class OnlyStrategyRevisionReader(Protocol):
    def exists(self, strategy_fingerprint: OnlyStrategyFingerprint | str) -> bool: ...

    def load_verified(self, strategy_fingerprint: OnlyStrategyFingerprint | str) -> OnlyStrategyRevision: ...


class _StrategyRevisionReader:
    def __init__(self, root: Path) -> None:
        self._root = root

    def exists(self, strategy_fingerprint: OnlyStrategyFingerprint | str) -> bool:
        return self._target(_fingerprint(strategy_fingerprint)).is_dir()

    def load_verified(self, strategy_fingerprint: OnlyStrategyFingerprint | str) -> OnlyStrategyRevision:
        fingerprint = _fingerprint(strategy_fingerprint)
        return self._read_verified(self._target(fingerprint), fingerprint)

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
            if not isinstance(payload, dict) or set(payload) != {
                "schema_version",
                "strategy_fingerprint",
                "revision",
            }:
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


class OnlyFrozenStrategyRevisionStore(_StrategyRevisionReader):
    """Runtime reader requiring both exact Revision and a verified Freeze relation."""

    def __init__(self, semantic_root: Path) -> None:
        super().__init__(semantic_root / "strategy" / "frozen-revisions")
        self._relations = _StrategyFreezeRelationReader(semantic_root)

    def exists(self, strategy_fingerprint: OnlyStrategyFingerprint | str) -> bool:
        try:
            self.load_verified(strategy_fingerprint)
        except OnlyStrategyStoreError as exc:
            if exc.code in {"STRATEGY_NOT_FOUND", "STRATEGY_FREEZE_RELATION_NOT_FOUND"}:
                return False
            raise
        return True

    def load_verified(self, strategy_fingerprint: OnlyStrategyFingerprint | str) -> OnlyStrategyRevision:
        revision = super().load_verified(strategy_fingerprint)
        self._relations.require_for_strategy(str(revision.strategy_fingerprint))
        return revision

    def freeze_relations(
        self, strategy_fingerprint: OnlyStrategyFingerprint | str
    ) -> tuple[OnlyStrategyFreezeRelation, ...]:
        fingerprint = _fingerprint(strategy_fingerprint)
        super().load_verified(fingerprint)
        return self._relations.require_for_strategy(fingerprint)

    def frozen_strategy_fingerprints(self) -> tuple[str, ...]:
        """Enumerate every verified frozen Strategy in canonical identity order."""

        root = self._root / "sha256"
        if root.is_symlink():
            raise OnlyStrategyStoreError("STRATEGY_CORRUPT", "frozen Strategy inventory")
        if not root.exists():
            return ()
        fingerprints: list[str] = []
        try:
            if root.is_symlink() or not root.is_dir():
                raise ValueError("frozen Strategy inventory root is invalid")
            for prefix in sorted(root.iterdir(), key=lambda item: item.name):
                if (
                    prefix.is_symlink()
                    or not prefix.is_dir()
                    or len(prefix.name) != 2
                    or any(char not in "0123456789abcdef" for char in prefix.name)
                ):
                    raise ValueError("unexpected frozen Strategy prefix")
                for target in sorted(prefix.iterdir(), key=lambda item: item.name):
                    _require_sha(target.name, "frozen Strategy fingerprint")
                    if target.name[:2] != prefix.name or target.is_symlink() or not target.is_dir():
                        raise ValueError("frozen Strategy path identity is invalid")
                    revision = self.load_verified(target.name)
                    fingerprint = str(revision.strategy_fingerprint)
                    if fingerprint != target.name:
                        raise ValueError("frozen Strategy inventory identity differs")
                    fingerprints.append(fingerprint)
        except OnlyStrategyStoreError:
            raise
        except Exception as exc:
            raise OnlyStrategyStoreError("STRATEGY_CORRUPT", "frozen Strategy inventory") from exc
        if len(fingerprints) != len(set(fingerprints)):
            raise OnlyStrategyStoreError("STRATEGY_CORRUPT", "duplicate frozen Strategy identity")
        return tuple(sorted(fingerprints))


class _StrategyFreezeRelationReader:
    def __init__(self, semantic_root: Path) -> None:
        self._root = semantic_root / "strategy" / "freeze-relations" / "sha256"

    def load_verified(self, relation_fingerprint: str) -> OnlyStrategyFreezeRelation:
        _require_sha(relation_fingerprint, "Freeze relation fingerprint")
        target = self._root / relation_fingerprint[:2] / relation_fingerprint
        if not target.is_dir():
            raise OnlyStrategyStoreError("STRATEGY_FREEZE_RELATION_NOT_FOUND", relation_fingerprint)
        try:
            manifest = target / "manifest.json"
            if target.is_symlink() or manifest.is_symlink():
                raise ValueError("Strategy Freeze Relation may not contain symlinks")
            if {item.name for item in target.iterdir()} != {"manifest.json"} or not manifest.is_file():
                raise ValueError("unexpected Strategy Freeze Relation entries")
            raw = manifest.read_text(encoding="utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("Strategy Freeze Relation must be an object")
            relation = OnlyStrategyFreezeRelation.from_dict(payload)
            if relation.relation_fingerprint != relation_fingerprint or raw != only_canonical_json(payload):
                raise ValueError("Strategy Freeze Relation path/content identity differs")
            return relation
        except OnlyStrategyStoreError:
            raise
        except Exception as exc:
            raise OnlyStrategyStoreError("STRATEGY_FREEZE_RELATION_CORRUPT", relation_fingerprint) from exc

    def require_for_strategy(self, strategy_fingerprint: str) -> tuple[OnlyStrategyFreezeRelation, ...]:
        if not self._root.exists():
            raise OnlyStrategyStoreError("STRATEGY_FREEZE_RELATION_NOT_FOUND", strategy_fingerprint)
        matches: list[OnlyStrategyFreezeRelation] = []
        try:
            for prefix in sorted(self._root.iterdir(), key=lambda item: item.name):
                if prefix.is_symlink() or not prefix.is_dir() or len(prefix.name) != 2:
                    raise ValueError("unexpected Strategy Freeze Relation prefix")
                for target in sorted(prefix.iterdir(), key=lambda item: item.name):
                    relation = self.load_verified(target.name)
                    if relation.strategy_fingerprint == strategy_fingerprint:
                        matches.append(relation)
        except OnlyStrategyStoreError:
            raise
        except Exception as exc:
            raise OnlyStrategyStoreError("STRATEGY_FREEZE_RELATION_CORRUPT", strategy_fingerprint) from exc
        if not matches:
            raise OnlyStrategyStoreError("STRATEGY_FREEZE_RELATION_NOT_FOUND", strategy_fingerprint)
        return tuple(sorted(matches, key=lambda item: item.relation_fingerprint))


@dataclass(frozen=True, slots=True)
class _OnlyFrozenStrategyPublication:
    revision: OnlyStrategyRevision
    relation: OnlyStrategyFreezeRelation
    seal: object


_FREEZE_PUBLICATION_SEAL = object()


def _only_authorize_frozen_strategy_publication(
    revision: OnlyStrategyRevision,
    relation: OnlyStrategyFreezeRelation,
) -> _OnlyFrozenStrategyPublication:
    if relation.strategy_fingerprint != str(revision.strategy_fingerprint):
        raise OnlyStrategyStoreError("STRATEGY_FREEZE_RELATION_CORRUPT", relation.relation_fingerprint)
    return _OnlyFrozenStrategyPublication(revision, relation, _FREEZE_PUBLICATION_SEAL)


class _OnlyFrozenStrategyPublisher:
    """Internal publisher capability composed only into Strategy Freeze."""

    def __init__(self, reader: OnlyFrozenStrategyRevisionStore) -> None:
        self._reader = reader

    def publish_verified(self, publication: _OnlyFrozenStrategyPublication) -> OnlyStrategyRevision:
        if (
            not isinstance(publication, _OnlyFrozenStrategyPublication)
            or publication.seal is not _FREEZE_PUBLICATION_SEAL
        ):
            raise OnlyStrategyStoreError(
                "STRATEGY_PUBLICATION_UNAUTHORIZED", "Frozen publication requires verified Freeze authority"
            )
        revision = publication.revision
        self._publish_relation(publication.relation)
        fingerprint = str(revision.strategy_fingerprint)
        target = self._reader._target(fingerprint)
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
            self._reader._read_verified(stage, fingerprint)
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
            return self._reader.load_verified(fingerprint)
        except OnlyStrategyStoreError:
            raise
        except Exception as exc:
            raise OnlyStrategyStoreError("STRATEGY_PUBLICATION_CONFLICT", "atomic publication failed") from exc
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def _publish_relation(self, relation: OnlyStrategyFreezeRelation) -> OnlyStrategyFreezeRelation:
        fingerprint = relation.relation_fingerprint
        target = self._reader._relations._root / fingerprint[:2] / fingerprint
        if target.exists() or target.is_symlink():
            existing = self._reader._relations.load_verified(fingerprint)
            if existing != relation:
                raise OnlyStrategyStoreError("STRATEGY_FREEZE_RELATION_CORRUPT", fingerprint)
            return existing
        target.parent.mkdir(parents=True, exist_ok=True)
        staging_root = self._reader._relations._root.parent / ".freeze-relation-staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        stage = staging_root / f"stage-{uuid.uuid4().hex}"
        try:
            stage.mkdir()
            path = stage / "manifest.json"
            with path.open("x", encoding="utf-8") as stream:
                stream.write(only_canonical_json(relation.to_dict()))
                stream.flush()
                os.fsync(stream.fileno())
            # Validate the staged bytes directly before the atomic rename.
            payload = json.loads(path.read_text(encoding="utf-8"))
            if OnlyStrategyFreezeRelation.from_dict(payload) != relation:
                raise ValueError("staged Strategy Freeze Relation differs")
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
                existing = self._reader._relations.load_verified(fingerprint)
                if existing != relation:
                    raise OnlyStrategyStoreError("STRATEGY_FREEZE_RELATION_CORRUPT", fingerprint) from None
                return existing
            parent = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
            return self._reader._relations.load_verified(fingerprint)
        except OnlyStrategyStoreError:
            raise
        except Exception as exc:
            raise OnlyStrategyStoreError("STRATEGY_FREEZE_RELATION_CORRUPT", fingerprint) from exc
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def _resolve_existing(self, candidate: OnlyStrategyRevision) -> OnlyStrategyRevision:
        fingerprint = str(candidate.strategy_fingerprint)
        existing = self._reader.load_verified(fingerprint)
        if existing.to_dict() != candidate.to_dict():
            raise OnlyStrategyStoreError("STRATEGY_PUBLICATION_CONFLICT", fingerprint)
        return existing


def _only_compose_frozen_strategy_authority(
    semantic_root: Path,
) -> tuple[OnlyFrozenStrategyRevisionStore, _OnlyFrozenStrategyPublisher]:
    reader = OnlyFrozenStrategyRevisionStore(semantic_root)
    return reader, _OnlyFrozenStrategyPublisher(reader)


def _fingerprint(value: OnlyStrategyFingerprint | str) -> str:
    try:
        return str(value if isinstance(value, OnlyStrategyFingerprint) else OnlyStrategyFingerprint(value))
    except (TypeError, ValueError) as exc:
        raise OnlyStrategyStoreError("STRATEGY_NOT_FOUND", "invalid Strategy fingerprint") from exc


def _require_sha(value: str, name: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lower-case SHA256")


__all__ = ["OnlyFrozenStrategyRevisionStore", "OnlyStrategyRevisionReader"]
