"""Composition-root factory for Runtime-owned execution transaction stores."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from onlyalpha.config.execution_store import OnlyExecutionStoreBackend, OnlyExecutionStoreConfig
from onlyalpha.domain.enums import OnlyRuntimeMode
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyEngineId, OnlyRuntimeId

from .transaction_store import (
    OnlyExecutionTransactionStorePort,
    OnlyInMemoryExecutionTransactionStore,
    OnlySqliteExecutionTransactionStore,
)


@dataclass(frozen=True, slots=True)
class OnlyExecutionTransactionStoreCreateRequest:
    engine_id: OnlyEngineId
    runtime_id: OnlyRuntimeId
    runtime_mode: OnlyRuntimeMode
    config: OnlyExecutionStoreConfig
    state_root: Path
    config_fingerprint: str
    base_currency: str
    account_id: OnlyAccountId
    market_profile_id: str

    @property
    def identity(self) -> dict[str, str]:
        return {
            "engine_id": str(self.engine_id),
            "runtime_id": str(self.runtime_id),
            "runtime_mode": self.runtime_mode.value,
            "config_fingerprint": self.config_fingerprint,
            "base_currency": self.base_currency,
            "account_id": str(self.account_id),
            "market_profile_id": self.market_profile_id,
        }


class OnlyExecutionTransactionStoreFactory(Protocol):
    def validate(self, config: OnlyExecutionStoreConfig) -> None: ...

    def create(self, request: OnlyExecutionTransactionStoreCreateRequest) -> OnlyExecutionTransactionStorePort: ...


class OnlyDefaultExecutionTransactionStoreFactory:
    def validate(self, config: OnlyExecutionStoreConfig) -> None:
        # Dataclass construction owns lexical validation. This method is
        # deliberately side-effect free for Engine.validate().
        if not isinstance(config.backend, OnlyExecutionStoreBackend):
            raise ValueError(f"unsupported execution Store backend: {config.backend}")

    def create(self, request: OnlyExecutionTransactionStoreCreateRequest) -> OnlyExecutionTransactionStorePort:
        self.validate(request.config)
        if request.config.backend is OnlyExecutionStoreBackend.MEMORY:
            return OnlyInMemoryExecutionTransactionStore()
        path = self.resolve_path(request)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.is_dir():
            raise ValueError(f"execution Store path is a directory: {path}")
        return OnlySqliteExecutionTransactionStore(path, identity=request.identity)

    @staticmethod
    def resolve_path(request: OnlyExecutionTransactionStoreCreateRequest) -> Path:
        relative = Path(request.config.path or "execution.sqlite3")
        state_root = request.state_root.resolve()
        path = (state_root / relative).resolve()
        if not path.is_relative_to(state_root):
            raise ValueError("execution Store path escapes Runtime state root")
        return path
