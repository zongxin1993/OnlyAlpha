"""Composition-root factory for the unique Runtime persistence store."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from onlyalpha.config.persistence import OnlyRuntimePersistenceBackend, OnlyRuntimePersistenceConfig
from onlyalpha.domain.enums import OnlyRuntimeMode
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyEngineId, OnlyRuntimeId

from .store import (
    OnlyInMemoryRuntimePersistenceStore,
    OnlyRuntimePersistenceStorePort,
    OnlySqliteRuntimePersistenceStore,
)


@dataclass(frozen=True, slots=True)
class OnlyRuntimePersistenceStoreCreateRequest:
    engine_id: OnlyEngineId
    runtime_id: OnlyRuntimeId
    runtime_mode: OnlyRuntimeMode
    config: OnlyRuntimePersistenceConfig
    state_root: Path
    config_fingerprint: str
    participant_registry_fingerprint: str | None
    base_currency: str
    account_id: OnlyAccountId
    market_profile_id: str

    @property
    def identity(self) -> dict[str, str]:
        identity = {
            "engine_id": str(self.engine_id),
            "runtime_id": str(self.runtime_id),
            "runtime_mode": self.runtime_mode.value,
            "config_fingerprint": self.config_fingerprint,
            "base_currency": self.base_currency,
            "account_id": str(self.account_id),
            "market_profile_id": self.market_profile_id,
        }
        if self.participant_registry_fingerprint is not None:
            identity["participant_registry_fingerprint"] = self.participant_registry_fingerprint
        return identity


class OnlyRuntimePersistenceStoreFactory(Protocol):
    def validate(self, config: OnlyRuntimePersistenceConfig) -> None: ...

    def create(self, request: OnlyRuntimePersistenceStoreCreateRequest) -> OnlyRuntimePersistenceStorePort: ...


class OnlyDefaultRuntimePersistenceStoreFactory:
    def validate(self, config: OnlyRuntimePersistenceConfig) -> None:
        # Dataclass construction owns lexical validation. This method is
        # deliberately side-effect free for Engine.validate().
        if not isinstance(config.backend, OnlyRuntimePersistenceBackend):
            raise ValueError(f"unsupported Runtime persistence backend: {config.backend}")

    def create(self, request: OnlyRuntimePersistenceStoreCreateRequest) -> OnlyRuntimePersistenceStorePort:
        self.validate(request.config)
        if request.config.backend is OnlyRuntimePersistenceBackend.MEMORY:
            return OnlyInMemoryRuntimePersistenceStore()
        path = self.resolve_path(request)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.is_dir():
            raise ValueError(f"Runtime persistence path is a directory: {path}")
        return OnlySqliteRuntimePersistenceStore(path, identity=request.identity)

    @staticmethod
    def resolve_path(request: OnlyRuntimePersistenceStoreCreateRequest) -> Path:
        relative = Path(request.config.path or "runtime.sqlite3")
        state_root = request.state_root.resolve()
        path = (state_root / relative).resolve()
        if not path.is_relative_to(state_root):
            raise ValueError("Runtime persistence path escapes Runtime state root")
        return path
