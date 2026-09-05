"""Append-only durable Runtime Generation lifecycle and new-work activation authority."""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from threading import RLock
from types import MappingProxyType
from typing import Any, cast

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.runtime.generation import OnlyRuntimeGenerationManifest
from onlyalpha.strategy.revision import OnlyStrategyRevision

_LOCKS_GUARD = RLock()
_LOCKS: dict[Path, RLock] = {}


class OnlyGenerationState(StrEnum):
    PREPARING = "PREPARING"
    READY = "READY"
    ACTIVE_FOR_NEW_WORK = "ACTIVE_FOR_NEW_WORK"
    DRAINING = "DRAINING"
    RETIRED = "RETIRED"
    REJECTED = "REJECTED"


class _EventKind(StrEnum):
    PREPARED = "GenerationPrepared"
    VALIDATED = "GenerationValidated"
    ACTIVATED = "GenerationActivated"
    REJECTED = "GenerationRejected"
    RETIRED = "GenerationRetired"
    WORK_BOUND = "RuntimeWorkBound"
    WORK_RELEASED = "RuntimeWorkReleased"


@dataclass(frozen=True, slots=True)
class OnlyGenerationEvent:
    sequence: int
    kind: str
    occurred_at: datetime
    actor: str
    generation_fingerprint: str
    previous_event_fingerprint: str | None
    expected_current: str | None = None
    work_id: str | None = None
    reason: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.sequence < 1 or self.kind not in {item.value for item in _EventKind}:
            raise ValueError("RUNTIME_GENERATION_EVENT_INVALID")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() != UTC.utcoffset(self.occurred_at):
            raise ValueError("RUNTIME_GENERATION_EVENT_INVALID")
        if not self.actor.strip():
            raise ValueError("RUNTIME_GENERATION_EVENT_INVALID")
        _sha(self.generation_fingerprint, "RUNTIME_GENERATION_EVENT_INVALID")
        for value in (self.previous_event_fingerprint, self.expected_current):
            if value is not None:
                _sha(value, "RUNTIME_GENERATION_EVENT_INVALID")
        if self.kind in {_EventKind.WORK_BOUND.value, _EventKind.WORK_RELEASED.value}:
            if self.work_id is None or not self.work_id.strip():
                raise ValueError("RUNTIME_GENERATION_EVENT_INVALID")
        elif self.work_id is not None:
            raise ValueError("RUNTIME_GENERATION_EVENT_INVALID")
        if self.kind == _EventKind.ACTIVATED.value and self.expected_current == self.generation_fingerprint:
            raise ValueError("RUNTIME_GENERATION_EVENT_INVALID")

    @property
    def event_fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict(include_fingerprint=False))

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "kind": self.kind,
            "occurred_at": self.occurred_at.isoformat(),
            "actor": self.actor,
            "generation_fingerprint": self.generation_fingerprint,
            "previous_event_fingerprint": self.previous_event_fingerprint,
            "expected_current": self.expected_current,
            "work_id": self.work_id,
            "reason": self.reason,
        }
        if include_fingerprint:
            result["event_fingerprint"] = self.event_fingerprint
        return result

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyGenerationEvent:
        expected = {
            "schema_version",
            "sequence",
            "kind",
            "occurred_at",
            "actor",
            "generation_fingerprint",
            "previous_event_fingerprint",
            "expected_current",
            "work_id",
            "reason",
            "event_fingerprint",
        }
        if set(payload) != expected:
            raise ValueError("RUNTIME_GENERATION_EVENT_INVALID")
        result = cls(
            sequence=_integer(payload, "sequence"),
            kind=_string(payload, "kind"),
            occurred_at=datetime.fromisoformat(_string(payload, "occurred_at")),
            actor=_string(payload, "actor"),
            generation_fingerprint=_string(payload, "generation_fingerprint"),
            previous_event_fingerprint=_optional_string(payload, "previous_event_fingerprint"),
            expected_current=_optional_string(payload, "expected_current"),
            work_id=_optional_string(payload, "work_id"),
            reason=_optional_string(payload, "reason"),
            schema_version=_integer(payload, "schema_version"),
        )
        if _string(payload, "event_fingerprint") != result.event_fingerprint:
            raise ValueError("RUNTIME_GENERATION_EVENT_CHAIN_CORRUPT")
        return result


@dataclass(frozen=True, slots=True)
class OnlyRuntimeWorkBinding:
    work_id: str
    runtime_generation_fingerprint: str
    active: bool


@dataclass(frozen=True, slots=True)
class OnlyGenerationProjection:
    active_for_new_work: str | None
    states: Mapping[str, OnlyGenerationState]
    work_bindings: Mapping[str, OnlyRuntimeWorkBinding]
    event_head: str | None

    def state(self, generation_fingerprint: str) -> OnlyGenerationState:
        try:
            return self.states[generation_fingerprint]
        except KeyError as exc:
            raise KeyError(generation_fingerprint) from exc


@dataclass(frozen=True, slots=True)
class OnlyRuntimeGenerationRegistry:
    root: Path

    @property
    def _ledger(self) -> Path:
        return self.root / "generation-events.jsonl"

    @property
    def _manifest_root(self) -> Path:
        return self.root / "runtime-generations"

    def prepare(self, manifest: OnlyRuntimeGenerationManifest, *, actor: str, occurred_at: datetime) -> None:
        fingerprint = manifest.runtime_generation_fingerprint
        with self._locked():
            self._commit_manifest(manifest)
            projection, events = self._replay()
            if fingerprint in projection.states:
                if self.load_manifest(fingerprint) != manifest:
                    raise ValueError("RUNTIME_GENERATION_MANIFEST_CONFLICT")
                return
            self._append(self._event(events, _EventKind.PREPARED, fingerprint, actor, occurred_at))

    def mark_ready(self, generation_fingerprint: str, *, actor: str, occurred_at: datetime) -> None:
        with self._locked():
            projection, events = self._replay()
            state = projection.state(generation_fingerprint)
            if state is OnlyGenerationState.READY:
                return
            if state is not OnlyGenerationState.PREPARING:
                raise ValueError("RUNTIME_GENERATION_NOT_PREPARING")
            self.load_manifest(generation_fingerprint)
            self._append(self._event(events, _EventKind.VALIDATED, generation_fingerprint, actor, occurred_at))

    def reject(self, generation_fingerprint: str, *, actor: str, occurred_at: datetime, reason: str) -> None:
        if not reason.strip():
            raise ValueError("RUNTIME_GENERATION_REJECTION_REASON_REQUIRED")
        with self._locked():
            projection, events = self._replay()
            state = projection.state(generation_fingerprint)
            if state is OnlyGenerationState.REJECTED:
                return
            if state is not OnlyGenerationState.PREPARING:
                raise ValueError("RUNTIME_GENERATION_REJECTION_CONFLICT")
            self._append(
                self._event(events, _EventKind.REJECTED, generation_fingerprint, actor, occurred_at, reason=reason)
            )

    def activate_for_new_work(
        self,
        *,
        expected_current: str | None,
        target: str,
        actor: str,
        occurred_at: datetime,
        reason: str | None = None,
        fault: Callable[[str], None] | None = None,
    ) -> None:
        if fault is not None:
            fault("before_commit")
        with self._locked():
            projection, events = self._replay()
            actual = projection.active_for_new_work
            if actual == target:
                matching_activation = next(
                    (
                        event
                        for event in reversed(events)
                        if event.kind == _EventKind.ACTIVATED.value
                        and event.generation_fingerprint == target
                        and event.expected_current == expected_current
                    ),
                    None,
                )
                if matching_activation is not None:
                    return
            if actual != expected_current:
                raise ValueError("GENERATION_ACTIVATION_CONFLICT")
            state = projection.state(target)
            if state not in {OnlyGenerationState.READY, OnlyGenerationState.DRAINING}:
                raise ValueError("RUNTIME_GENERATION_NOT_READY")
            event = self._event(
                events,
                _EventKind.ACTIVATED,
                target,
                actor,
                occurred_at,
                expected_current=expected_current,
                reason=reason,
            )
            self._append(event)
        if fault is not None:
            fault("after_commit")

    def bind_new_work(self, work_id: str, *, actor: str, occurred_at: datetime) -> OnlyRuntimeWorkBinding:
        if not work_id.strip():
            raise ValueError("RUNTIME_WORK_ID_INVALID")
        with self._locked():
            projection, events = self._replay()
            existing = projection.work_bindings.get(work_id)
            if existing is not None:
                return existing
            active = projection.active_for_new_work
            if active is None:
                raise ValueError("RUNTIME_GENERATION_NOT_ACTIVE")
            self._append(self._event(events, _EventKind.WORK_BOUND, active, actor, occurred_at, work_id=work_id))
            return OnlyRuntimeWorkBinding(work_id, active, True)

    def release_work(self, work_id: str, *, actor: str, occurred_at: datetime) -> OnlyRuntimeWorkBinding:
        with self._locked():
            projection, events = self._replay()
            try:
                existing = projection.work_bindings[work_id]
            except KeyError as exc:
                raise KeyError(work_id) from exc
            if not existing.active:
                return existing
            self._append(
                self._event(
                    events,
                    _EventKind.WORK_RELEASED,
                    existing.runtime_generation_fingerprint,
                    actor,
                    occurred_at,
                    work_id=work_id,
                )
            )
            return OnlyRuntimeWorkBinding(work_id, existing.runtime_generation_fingerprint, False)

    def require_work_generation(
        self, work_id: str, process_generation_fingerprint: str
    ) -> OnlyRuntimeGenerationManifest:
        """Fail before execution when a process does not host the work's immutable generation."""

        with self._locked(shared=True):
            projection, _ = self._replay()
            try:
                binding = projection.work_bindings[work_id]
            except KeyError as exc:
                raise ValueError("RUNTIME_WORK_GENERATION_UNBOUND") from exc
            if not binding.active or binding.runtime_generation_fingerprint != process_generation_fingerprint:
                raise ValueError("RUNTIME_WORK_GENERATION_MISMATCH")
            return self.load_manifest(process_generation_fingerprint)

    def retire(self, generation_fingerprint: str, *, actor: str, occurred_at: datetime) -> None:
        with self._locked():
            projection, events = self._replay()
            if projection.state(generation_fingerprint) is OnlyGenerationState.RETIRED:
                return
            if projection.active_for_new_work == generation_fingerprint or any(
                item.active and item.runtime_generation_fingerprint == generation_fingerprint
                for item in projection.work_bindings.values()
            ):
                raise ValueError("RUNTIME_GENERATION_STILL_REQUIRED")
            if projection.state(generation_fingerprint) is not OnlyGenerationState.DRAINING:
                raise ValueError("RUNTIME_GENERATION_NOT_DRAINING")
            self._append(self._event(events, _EventKind.RETIRED, generation_fingerprint, actor, occurred_at))

    def projection(self) -> OnlyGenerationProjection:
        with self._locked(shared=True):
            return self._replay()[0]

    def load_manifest(self, generation_fingerprint: str) -> OnlyRuntimeGenerationManifest:
        path = self._manifest_root / f"{generation_fingerprint}.json"
        try:
            payload: Any = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError
            manifest = OnlyRuntimeGenerationManifest.from_dict(cast(dict[str, object], payload))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError("RUNTIME_GENERATION_MANIFEST_MISMATCH") from exc
        if manifest.runtime_generation_fingerprint != generation_fingerprint:
            raise ValueError("RUNTIME_GENERATION_MANIFEST_MISMATCH")
        return manifest

    def manifests(self) -> tuple[OnlyRuntimeGenerationManifest, ...]:
        projection = self.projection()
        return tuple(self.load_manifest(fingerprint) for fingerprint in sorted(projection.states))

    def _commit_manifest(self, manifest: OnlyRuntimeGenerationManifest) -> None:
        self._manifest_root.mkdir(parents=True, exist_ok=True)
        path = self._manifest_root / f"{manifest.runtime_generation_fingerprint}.json"
        content = (only_canonical_json(manifest.to_dict()) + "\n").encode()
        _write_once(path, content, "RUNTIME_GENERATION_MANIFEST_CONFLICT")

    def _replay(self) -> tuple[OnlyGenerationProjection, tuple[OnlyGenerationEvent, ...]]:
        events = self._read_events()
        lifecycle: dict[str, OnlyGenerationState] = {}
        bindings: dict[str, OnlyRuntimeWorkBinding] = {}
        active: str | None = None
        for event in events:
            generation = event.generation_fingerprint
            kind = _EventKind(event.kind)
            if kind is _EventKind.PREPARED:
                if generation in lifecycle:
                    raise ValueError("RUNTIME_GENERATION_EVENT_ORDER_INVALID")
                lifecycle[generation] = OnlyGenerationState.PREPARING
            elif generation not in lifecycle:
                raise ValueError("RUNTIME_GENERATION_EVENT_ORDER_INVALID")
            elif kind is _EventKind.VALIDATED:
                if lifecycle[generation] is not OnlyGenerationState.PREPARING:
                    raise ValueError("RUNTIME_GENERATION_EVENT_ORDER_INVALID")
                lifecycle[generation] = OnlyGenerationState.READY
            elif kind is _EventKind.REJECTED:
                if lifecycle[generation] is not OnlyGenerationState.PREPARING:
                    raise ValueError("RUNTIME_GENERATION_EVENT_ORDER_INVALID")
                lifecycle[generation] = OnlyGenerationState.REJECTED
            elif kind is _EventKind.ACTIVATED:
                if active != event.expected_current:
                    raise ValueError("RUNTIME_GENERATION_EVENT_ORDER_INVALID")
                if lifecycle[generation] not in {OnlyGenerationState.READY, OnlyGenerationState.DRAINING}:
                    raise ValueError("RUNTIME_GENERATION_EVENT_ORDER_INVALID")
                if active is not None:
                    lifecycle[active] = OnlyGenerationState.DRAINING
                active = generation
                lifecycle[generation] = OnlyGenerationState.ACTIVE_FOR_NEW_WORK
            elif kind is _EventKind.WORK_BOUND:
                assert event.work_id is not None
                if active != generation or event.work_id in bindings:
                    raise ValueError("RUNTIME_GENERATION_EVENT_ORDER_INVALID")
                bindings[event.work_id] = OnlyRuntimeWorkBinding(event.work_id, generation, True)
            elif kind is _EventKind.WORK_RELEASED:
                assert event.work_id is not None
                binding = bindings.get(event.work_id)
                if binding is None or not binding.active or binding.runtime_generation_fingerprint != generation:
                    raise ValueError("RUNTIME_GENERATION_EVENT_ORDER_INVALID")
                bindings[event.work_id] = OnlyRuntimeWorkBinding(event.work_id, generation, False)
            elif kind is _EventKind.RETIRED:
                if active == generation or lifecycle[generation] is not OnlyGenerationState.DRAINING:
                    raise ValueError("RUNTIME_GENERATION_EVENT_ORDER_INVALID")
                if any(item.active and item.runtime_generation_fingerprint == generation for item in bindings.values()):
                    raise ValueError("RUNTIME_GENERATION_EVENT_ORDER_INVALID")
                lifecycle[generation] = OnlyGenerationState.RETIRED
        for generation in lifecycle:
            self.load_manifest(generation)
        return (
            OnlyGenerationProjection(
                active,
                MappingProxyType(dict(lifecycle)),
                MappingProxyType(dict(bindings)),
                None if not events else events[-1].event_fingerprint,
            ),
            events,
        )

    def _read_events(self) -> tuple[OnlyGenerationEvent, ...]:
        if not self._ledger.exists():
            return ()
        result = []
        previous: str | None = None
        try:
            lines = self._ledger.read_text(encoding="utf-8").splitlines()
            for sequence, line in enumerate(lines, start=1):
                payload: Any = json.loads(line)
                if not isinstance(payload, dict):
                    raise ValueError
                event = OnlyGenerationEvent.from_dict(cast(dict[str, object], payload))
                if event.sequence != sequence or event.previous_event_fingerprint != previous:
                    raise ValueError
                previous = event.event_fingerprint
                result.append(event)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError("RUNTIME_GENERATION_EVENT_CHAIN_CORRUPT") from exc
        return tuple(result)

    @staticmethod
    def _event(
        events: tuple[OnlyGenerationEvent, ...],
        kind: _EventKind,
        generation_fingerprint: str,
        actor: str,
        occurred_at: datetime,
        *,
        expected_current: str | None = None,
        work_id: str | None = None,
        reason: str | None = None,
    ) -> OnlyGenerationEvent:
        return OnlyGenerationEvent(
            sequence=len(events) + 1,
            kind=kind.value,
            occurred_at=occurred_at,
            actor=actor,
            generation_fingerprint=generation_fingerprint,
            previous_event_fingerprint=None if not events else events[-1].event_fingerprint,
            expected_current=expected_current,
            work_id=work_id,
            reason=reason,
        )

    def _append(self, event: OnlyGenerationEvent) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        encoded = (only_canonical_json(event.to_dict()) + "\n").encode()
        descriptor = os.open(self._ledger, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            view = memoryview(encoded)
            while view:
                written = os.write(descriptor, view)
                if written < 1:
                    raise OSError("generation event append made no progress")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _fsync_directory(self.root)

    @contextmanager
    def _locked(self, *, shared: bool = False) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        lock_path = (self.root / ".generation-authority.lock").resolve()
        with _LOCKS_GUARD:
            local = _LOCKS.setdefault(lock_path, RLock())
        with local:
            descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)


@dataclass(frozen=True, slots=True)
class OnlyHistoricalRuntimeGenerationResolver:
    registry: OnlyRuntimeGenerationRegistry

    def resolve(
        self,
        revision: OnlyStrategyRevision,
        *,
        exact_generation_fingerprint: str | None = None,
    ) -> OnlyRuntimeGenerationManifest:
        required = {
            fingerprint
            for binding in revision.implementation_bindings
            for fingerprint in (
                binding.research_implementation_fingerprint,
                binding.trading_implementation_fingerprint,
            )
        }
        projection = self.registry.projection()
        executable = {
            fingerprint
            for fingerprint, state in projection.states.items()
            if state not in {OnlyGenerationState.PREPARING, OnlyGenerationState.REJECTED}
        }
        manifests = tuple(self.registry.load_manifest(fingerprint) for fingerprint in sorted(executable))
        if exact_generation_fingerprint is not None:
            manifests = tuple(
                item for item in manifests if item.runtime_generation_fingerprint == exact_generation_fingerprint
            )
        matches = tuple(
            manifest
            for manifest in manifests
            if required <= {implementation.implementation_fingerprint for implementation in manifest.implementations}
        )
        if not matches:
            raise ValueError("HISTORICAL_IMPLEMENTATION_UNAVAILABLE")
        if len(matches) != 1:
            raise ValueError("HISTORICAL_IMPLEMENTATION_AMBIGUOUS")
        return matches[0]


def _write_once(path: Path, content: bytes, conflict_code: str) -> None:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.read_bytes() != content:
            raise ValueError(conflict_code) from None
        return
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sha(value: object, code: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(code)
    return value


def _string(payload: Mapping[str, object], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str):
        raise ValueError("RUNTIME_GENERATION_EVENT_INVALID")
    return value


def _optional_string(payload: Mapping[str, object], key: str) -> str | None:
    value = payload[key]
    if value is not None and not isinstance(value, str):
        raise ValueError("RUNTIME_GENERATION_EVENT_INVALID")
    return value


def _integer(payload: Mapping[str, object], key: str) -> int:
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("RUNTIME_GENERATION_EVENT_INVALID")
    return value


__all__ = [name for name in globals() if name.startswith("Only")]
