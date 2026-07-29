"""Typed product configuration for Runtime persistence and checkpoints."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class OnlyRuntimePersistenceBackend(StrEnum):
    MEMORY = "MEMORY"
    SQLITE = "SQLITE"


@dataclass(frozen=True, slots=True)
class OnlyRuntimeCheckpointConfig:
    enabled: bool
    retain_last: int = 2

    def __post_init__(self) -> None:
        if self.retain_last < 1:
            raise ValueError("runtime.persistence.checkpoint.retain_last must be positive")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object] | None) -> OnlyRuntimeCheckpointConfig:
        raw = {} if value is None else value
        unknown = set(raw) - {"enabled", "retain_last"}
        if unknown:
            raise ValueError(f"runtime.persistence.checkpoint UNKNOWN_FIELD: {sorted(unknown)[0]}")
        enabled = raw.get("enabled", False)
        retain_last = raw.get("retain_last", 2)
        if not isinstance(enabled, bool):
            raise ValueError("runtime.persistence.checkpoint.enabled must be a boolean")
        if isinstance(retain_last, bool) or not isinstance(retain_last, int):
            raise ValueError("runtime.persistence.checkpoint.retain_last must be an integer")
        return cls(enabled, retain_last)

    def to_dict(self) -> dict[str, object]:
        return {"enabled": self.enabled, "retain_last": self.retain_last}


@dataclass(frozen=True, slots=True)
class OnlyRuntimePersistenceConfig:
    backend: OnlyRuntimePersistenceBackend = OnlyRuntimePersistenceBackend.MEMORY
    path: str | None = None
    checkpoint: OnlyRuntimeCheckpointConfig = OnlyRuntimeCheckpointConfig(False)

    def __post_init__(self) -> None:
        if self.backend is OnlyRuntimePersistenceBackend.MEMORY:
            if self.path is not None:
                raise ValueError("MEMORY runtime persistence does not accept path")
            if self.checkpoint.enabled:
                raise ValueError("MEMORY runtime persistence requires checkpoint.enabled=false")
            return
        if not self.checkpoint.enabled:
            raise ValueError("SQLITE runtime persistence requires checkpoint.enabled=true")
        if self.path is None:
            return
        value = self.path.strip()
        if not value:
            raise ValueError("runtime persistence path cannot be empty")
        candidate = Path(value)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("runtime persistence path must stay relative to the Runtime state root")
        object.__setattr__(self, "path", value)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object] | None) -> OnlyRuntimePersistenceConfig:
        raw = {} if value is None else value
        unknown = set(raw) - {"backend", "path", "checkpoint"}
        if unknown:
            raise ValueError(f"runtime.persistence UNKNOWN_FIELD: {sorted(unknown)[0]}")
        backend_value = raw.get("backend", OnlyRuntimePersistenceBackend.MEMORY.value)
        if not isinstance(backend_value, str):
            raise ValueError("runtime.persistence.backend must be a string")
        try:
            backend = OnlyRuntimePersistenceBackend(backend_value.upper())
        except ValueError as exc:
            raise ValueError(f"unsupported runtime persistence backend: {backend_value}") from exc
        path = raw.get("path")
        if path is not None and not isinstance(path, str):
            raise ValueError("runtime.persistence.path must be a string")
        checkpoint_raw = raw.get("checkpoint")
        if checkpoint_raw is not None and not isinstance(checkpoint_raw, Mapping):
            raise ValueError("runtime.persistence.checkpoint must be a mapping")
        checkpoint = OnlyRuntimeCheckpointConfig.from_mapping(checkpoint_raw)
        return cls(backend, path, checkpoint)

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "backend": self.backend.value,
            "checkpoint": self.checkpoint.to_dict(),
        }
        if self.path is not None:
            result["path"] = self.path
        return result
