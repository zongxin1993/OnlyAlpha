"""Put-once exact persistence for immutable Novelty Policy revisions."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from onlyalpha.canonical import only_canonical_json

from .model import (
    NOVELTY_POLICY_SCHEMA_VERSION,
    OnlyNoveltyPolicyError,
    OnlyNoveltyPolicyInvalidError,
    OnlyNoveltyPolicyRevisionV1,
    OnlyNoveltyPolicySchemaUnsupportedError,
    _policy_id,
    _policy_version,
)


class OnlyNoveltyPolicyConflictError(OnlyNoveltyPolicyError):
    code = "NOVELTY_POLICY_CONFLICT"


class OnlyNoveltyPolicyNotFoundError(OnlyNoveltyPolicyError):
    code = "NOVELTY_POLICY_NOT_FOUND"


class OnlyNoveltyPolicyCorruptError(OnlyNoveltyPolicyError):
    code = "NOVELTY_POLICY_CORRUPT"


class OnlyNoveltyPolicyStore:
    def __init__(self, semantic_root: Path) -> None:
        self._semantic_root = semantic_root
        self._root = semantic_root / "research" / "novelty-policies"

    def put(self, policy: OnlyNoveltyPolicyRevisionV1) -> OnlyNoveltyPolicyRevisionV1:
        if not isinstance(policy, OnlyNoveltyPolicyRevisionV1):
            raise OnlyNoveltyPolicyInvalidError("put requires a validated V1 Policy Revision")
        policy = OnlyNoveltyPolicyRevisionV1.from_dict(policy.to_dict())
        target = self._target(policy.policy_id, policy.policy_version)
        self._require_safe(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._require_safe(target)
        lock = target.parent / f".{policy.policy_version}.lock"
        with self._locked(lock):
            if target.exists() or target.is_symlink():
                existing = self.load_exact(policy.policy_id, policy.policy_version)
                if existing != policy:
                    raise OnlyNoveltyPolicyConflictError(f"{policy.policy_id}@{policy.policy_version}")
                return existing
            stage = target.parent / f".{policy.policy_version}.{uuid.uuid4().hex}.stage"
            try:
                stage.mkdir(mode=0o700)
                manifest = stage / "manifest.json"
                with manifest.open("x", encoding="utf-8") as stream:
                    stream.write(only_canonical_json(policy.to_dict()))
                    stream.flush()
                    os.fsync(stream.fileno())
                self._fsync(stage)
                os.rename(stage, target)
                self._fsync(target.parent)
            except OnlyNoveltyPolicyError:
                raise
            except Exception as exc:
                raise OnlyNoveltyPolicyCorruptError(f"{policy.policy_id}@{policy.policy_version}") from exc
            finally:
                shutil.rmtree(stage, ignore_errors=True)
        return self.load_exact(policy.policy_id, policy.policy_version)

    def load_exact(self, policy_id: str, policy_version: str) -> OnlyNoveltyPolicyRevisionV1:
        target = self._target(policy_id, policy_version)
        self._require_safe(target)
        if not target.exists() and not target.is_symlink():
            raise OnlyNoveltyPolicyNotFoundError(f"{policy_id}@{policy_version}")
        try:
            manifest = target / "manifest.json"
            if (
                not target.is_dir()
                or manifest.is_symlink()
                or {item.name for item in target.iterdir()} != {"manifest.json"}
            ):
                raise ValueError("unexpected Policy revision shape")
            raw = manifest.read_text(encoding="utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, dict) or raw != only_canonical_json(payload):
                raise ValueError("Policy revision is not canonical")
            schema_version = payload.get("schema_version")
            if (
                isinstance(schema_version, bool)
                or not isinstance(schema_version, int)
                or schema_version != NOVELTY_POLICY_SCHEMA_VERSION
            ):
                raise OnlyNoveltyPolicySchemaUnsupportedError(str(schema_version))
            policy = OnlyNoveltyPolicyRevisionV1.from_dict(payload)
            if policy.policy_id != policy_id or policy.policy_version != policy_version:
                raise ValueError("Policy path identity differs")
            return policy
        except OnlyNoveltyPolicySchemaUnsupportedError:
            raise
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, OnlyNoveltyPolicyError) as exc:
            raise OnlyNoveltyPolicyCorruptError(f"{policy_id}@{policy_version}") from exc

    def _target(self, policy_id: object, policy_version: object) -> Path:
        return self._root / _policy_id(policy_id) / _policy_version(policy_version)

    def _require_safe(self, target: Path) -> None:
        paths = (self._semantic_root, self._semantic_root / "research", self._root, target.parent, target)
        if any(path.is_symlink() for path in paths):
            raise OnlyNoveltyPolicyCorruptError("unsafe authority path")

    @staticmethod
    @contextmanager
    def _locked(path: Path) -> Iterator[None]:
        if path.is_symlink():
            raise OnlyNoveltyPolicyCorruptError("unsafe authority lock")
        with path.open("a+b") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    @staticmethod
    def _fsync(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


__all__ = [name for name in globals() if name.startswith("OnlyNovelty")]
