"""Put-once, canonical-byte verified stores for immutable Agent context."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TypeVar, cast

from onlyalpha.canonical import only_canonical_json

from .errors import OnlyAgentContextError, OnlyAgentContextStoreError
from .model import (
    OnlyAgentOrchestrationResourceKind,
    OnlyAgentOrchestrationResourceV1,
    OnlyAgentResearchBriefV1,
    OnlyAgentSessionManifestV1,
)
from .verification import (
    OnlyAgentOrchestrationResourceReader,
    OnlyAgentResearchBriefReader,
    OnlyAgentResearchBriefReferenceReadersV1,
    OnlyVerifiedAgentDecisionContextV1,
    verify_agent_research_brief_references,
    verify_agent_session_bindings,
)

_T = TypeVar("_T")


class OnlyAgentCommitDisposition(StrEnum):
    CREATED = "CREATED"
    REUSED = "REUSED"


@dataclass(frozen=True, slots=True)
class OnlyAgentCommitOutcome:
    disposition: OnlyAgentCommitDisposition
    fingerprint: str


class _OnlyJsonPutOnceStore:
    def __init__(self, semantic_root: Path, relative_root: Path) -> None:
        self._semantic_root = semantic_root
        self._root = semantic_root / relative_root

    def commit(
        self,
        fingerprint: str,
        value: object,
        parser: Callable[[Mapping[str, object]], _T],
        missing_code: str,
        mismatch_code: str,
    ) -> OnlyAgentCommitOutcome:
        target = self._target(fingerprint, missing_code)
        lock = target.parent / f".{fingerprint}.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        with self._locked(lock):
            if target.exists():
                existing = self.load(fingerprint, parser, missing_code, mismatch_code)
                if only_canonical_json(_payload(existing)) != only_canonical_json(_payload(value)):
                    raise OnlyAgentContextStoreError(mismatch_code, fingerprint)
                return OnlyAgentCommitOutcome(OnlyAgentCommitDisposition.REUSED, fingerprint)
            stage = target.parent / f".{fingerprint}.{uuid.uuid4().hex}.stage"
            try:
                stage.mkdir(mode=0o700)
                manifest = stage / "manifest.json"
                manifest.write_text(only_canonical_json(_payload(value)), encoding="utf-8")
                with manifest.open("rb") as handle:
                    os.fsync(handle.fileno())
                parsed = json.loads(manifest.read_text(encoding="utf-8"))
                if not isinstance(parsed, dict):
                    raise ValueError("manifest is not an object")
                verified = parser(cast(Mapping[str, object], parsed))
                if _identity(verified) != fingerprint:
                    raise ValueError("staged identity differs")
                os.replace(stage, target)
                self._fsync(target.parent)
            except Exception as exc:
                if stage.exists():
                    shutil.rmtree(stage)
                if isinstance(exc, OnlyAgentContextError):
                    raise
                raise OnlyAgentContextStoreError(mismatch_code, fingerprint) from exc
        return OnlyAgentCommitOutcome(OnlyAgentCommitDisposition.CREATED, fingerprint)

    def load(
        self,
        fingerprint: str,
        parser: Callable[[Mapping[str, object]], _T],
        missing_code: str,
        mismatch_code: str,
    ) -> _T:
        target = self._target(fingerprint, missing_code)
        if not target.exists():
            raise OnlyAgentContextStoreError(missing_code, fingerprint)
        try:
            self._require_safe(target)
            manifest = target / "manifest.json"
            if (
                target.is_symlink()
                or not target.is_dir()
                or manifest.is_symlink()
                or {item.name for item in target.iterdir()} != {"manifest.json"}
            ):
                raise ValueError("unsafe or unexpected authority entries")
            raw = manifest.read_text(encoding="utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, dict) or raw != only_canonical_json(payload):
                raise ValueError("authority bytes are non-canonical")
            value = parser(cast(Mapping[str, object], payload))
            if _identity(value) != fingerprint:
                raise ValueError("authority path identity differs")
            return value
        except OnlyAgentContextStoreError:
            raise
        except Exception as exc:
            raise OnlyAgentContextStoreError(mismatch_code, fingerprint) from exc

    def _target(self, fingerprint: str, missing_code: str) -> Path:
        if len(fingerprint) != 64 or any(item not in "0123456789abcdef" for item in fingerprint):
            raise OnlyAgentContextStoreError(missing_code, "invalid fingerprint")
        target = self._root / "sha256" / fingerprint[:2] / fingerprint
        self._require_safe(target)
        return target

    def _require_safe(self, target: Path) -> None:
        if self._semantic_root.is_symlink() or self._root.is_symlink():
            raise OnlyAgentContextStoreError("AGENT_CONTEXT_UNSAFE_PATH", str(target))
        current = target
        while current != self._semantic_root:
            if current.exists() and current.is_symlink():
                raise OnlyAgentContextStoreError("AGENT_CONTEXT_UNSAFE_PATH", str(target))
            if current == current.parent:
                raise OnlyAgentContextStoreError("AGENT_CONTEXT_UNSAFE_PATH", str(target))
            current = current.parent

    @staticmethod
    @contextmanager
    def _locked(path: Path) -> Iterator[None]:
        with path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _fsync(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class OnlyJsonAgentOrchestrationResourceStore(OnlyAgentOrchestrationResourceReader):
    def __init__(self, semantic_root: Path) -> None:
        self._store = _OnlyJsonPutOnceStore(semantic_root, Path("research/agent-orchestration/resources"))

    def commit_resource(self, value: OnlyAgentOrchestrationResourceV1) -> OnlyAgentCommitOutcome:
        return self._store.commit(
            value.resource_fingerprint,
            value,
            OnlyAgentOrchestrationResourceV1.from_dict,
            "AGENT_ORCHESTRATION_RESOURCE_MISSING",
            "AGENT_ORCHESTRATION_RESOURCE_MISMATCH",
        )

    def load_resource_verified(
        self, resource_kind: OnlyAgentOrchestrationResourceKind, resource_fingerprint: str
    ) -> OnlyAgentOrchestrationResourceV1:
        value = self._store.load(
            resource_fingerprint,
            OnlyAgentOrchestrationResourceV1.from_dict,
            "AGENT_ORCHESTRATION_RESOURCE_MISSING",
            "AGENT_ORCHESTRATION_RESOURCE_MISMATCH",
        )
        if value.resource_kind is not resource_kind:
            raise OnlyAgentContextStoreError("AGENT_ORCHESTRATION_RESOURCE_MISMATCH", resource_fingerprint)
        return value


class OnlyJsonAgentResearchBriefStore(OnlyAgentResearchBriefReader):
    def __init__(self, semantic_root: Path, reference_readers: OnlyAgentResearchBriefReferenceReadersV1) -> None:
        self._store = _OnlyJsonPutOnceStore(semantic_root, Path("research/agent-orchestration/briefs"))
        self._reference_readers = reference_readers

    def commit_research_brief(self, value: OnlyAgentResearchBriefV1) -> OnlyAgentCommitOutcome:
        verify_agent_research_brief_references(value, self._reference_readers)
        return self._store.commit(
            value.research_brief_fingerprint,
            value,
            OnlyAgentResearchBriefV1.from_dict,
            "AGENT_RESEARCH_BRIEF_INVALID",
            "AGENT_RESEARCH_BRIEF_INVALID",
        )

    def load_research_brief_verified(self, research_brief_fingerprint: str) -> OnlyAgentResearchBriefV1:
        value = self._store.load(
            research_brief_fingerprint,
            OnlyAgentResearchBriefV1.from_dict,
            "AGENT_RESEARCH_BRIEF_INVALID",
            "AGENT_RESEARCH_BRIEF_INVALID",
        )
        verify_agent_research_brief_references(value, self._reference_readers)
        return value


class OnlyJsonAgentSessionManifestStore:
    def __init__(
        self,
        semantic_root: Path,
        *,
        briefs: OnlyAgentResearchBriefReader,
        resources: OnlyAgentOrchestrationResourceReader,
    ) -> None:
        self._store = _OnlyJsonPutOnceStore(semantic_root, Path("research/agent-orchestration/sessions"))
        self._briefs = briefs
        self._resources = resources

    def commit_session_manifest(self, value: OnlyAgentSessionManifestV1) -> OnlyAgentCommitOutcome:
        verify_agent_session_bindings(value, briefs=self._briefs, resources=self._resources)
        return self._store.commit(
            value.session_fingerprint,
            value,
            OnlyAgentSessionManifestV1.from_dict,
            "AGENT_SESSION_INVALID",
            "AGENT_SESSION_RESOURCE_MISMATCH",
        )

    def load_session_manifest_verified(self, session_fingerprint: str) -> OnlyVerifiedAgentDecisionContextV1:
        value = self._store.load(
            session_fingerprint,
            OnlyAgentSessionManifestV1.from_dict,
            "AGENT_SESSION_INVALID",
            "AGENT_SESSION_RESOURCE_MISMATCH",
        )
        return verify_agent_session_bindings(value, briefs=self._briefs, resources=self._resources)


def _payload(value: object) -> Mapping[str, object]:
    method = getattr(value, "to_dict", None)
    if not callable(method):
        raise TypeError("Agent authority value has no payload")
    payload = method()
    if not isinstance(payload, Mapping):
        raise TypeError("Agent authority payload must be an object")
    return cast(Mapping[str, object], payload)


def _identity(value: object) -> str:
    for name in ("session_fingerprint", "resource_fingerprint", "research_brief_fingerprint"):
        identity = getattr(value, name, None)
        if isinstance(identity, str):
            return identity
    raise TypeError("Agent authority value has no identity")


__all__ = [name for name in globals() if name.startswith("OnlyAgent") or name.startswith("OnlyJson")]
