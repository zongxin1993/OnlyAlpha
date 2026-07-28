"""Typed product configuration for the Runtime-owned execution transaction store."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class OnlyExecutionStoreBackend(StrEnum):
    MEMORY = "MEMORY"
    SQLITE = "SQLITE"


@dataclass(frozen=True, slots=True)
class OnlyExecutionStoreConfig:
    backend: OnlyExecutionStoreBackend = OnlyExecutionStoreBackend.MEMORY
    path: str | None = None

    def __post_init__(self) -> None:
        if self.backend is OnlyExecutionStoreBackend.MEMORY:
            if self.path is not None:
                raise ValueError("MEMORY execution store does not accept path")
            return
        if self.path is None:
            return
        value = self.path.strip()
        if not value:
            raise ValueError("execution store path cannot be empty")
        candidate = Path(value)
        if candidate.is_absolute():
            raise ValueError("execution store path must be relative to the Runtime state root")
        if ".." in candidate.parts:
            raise ValueError("execution store path cannot escape the Runtime state root")
        object.__setattr__(self, "path", value)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object] | None) -> OnlyExecutionStoreConfig:
        if value is None:
            return cls()
        unknown = set(value) - {"backend", "path"}
        if unknown:
            raise ValueError(f"execution_store UNKNOWN_FIELD: {sorted(unknown)[0]}")
        backend_value = value.get("backend", OnlyExecutionStoreBackend.MEMORY.value)
        if not isinstance(backend_value, str):
            raise ValueError("execution_store.backend must be a string")
        try:
            backend = OnlyExecutionStoreBackend(backend_value.upper())
        except ValueError as exc:
            raise ValueError(f"unsupported execution store backend: {backend_value}") from exc
        path_value = value.get("path")
        if path_value is not None and not isinstance(path_value, str):
            raise ValueError("execution_store.path must be a string")
        return cls(backend, path_value)

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"backend": self.backend.value}
        if self.path is not None:
            result["path"] = self.path
        return result
