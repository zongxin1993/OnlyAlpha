"""Minimal structural contracts at the Engine/Runtime product boundary."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from onlyalpha.plugin.lifecycle import OnlyPluginResourceSnapshot
from onlyalpha.runtime.result import OnlyRuntimeResult


class OnlyRuntimeEnvironment(Protocol):
    @property
    def runtime_type(self) -> str: ...

    @property
    def fingerprint(self) -> str: ...


class OnlyRuntimeProductPlan(Protocol):
    @property
    def runtime_id(self) -> object: ...

    @property
    def environment(self) -> OnlyRuntimeEnvironment: ...


class OnlyRuntimeProduct(Protocol):
    @property
    def runtime_id(self) -> object: ...

    @property
    def runtime_type(self) -> str: ...

    def initialize(self) -> None: ...

    def start(self) -> None: ...

    def close(self) -> None: ...


@runtime_checkable
class OnlyFiniteRuntime(Protocol):
    @property
    def is_finite_runtime(self) -> bool: ...

    def run(self) -> OnlyRuntimeResult: ...


@runtime_checkable
class OnlyWaitableRuntime(Protocol):
    def wait(self, timeout: float | None = None) -> None: ...


@runtime_checkable
class OnlyPluginResourceSnapshotRuntime(Protocol):
    @property
    def plugin_resource_snapshots(self) -> tuple[OnlyPluginResourceSnapshot, ...]: ...


__all__ = [
    "OnlyFiniteRuntime",
    "OnlyPluginResourceSnapshotRuntime",
    "OnlyRuntimeEnvironment",
    "OnlyRuntimeProduct",
    "OnlyRuntimeProductPlan",
    "OnlyWaitableRuntime",
]
