"""Runtime factory abstraction, registry, and structured build failures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.config import OnlyRuntimeAssemblyPlan
from onlyalpha.runtime.planning import OnlyRuntimePlan
from onlyalpha.runtime.runtime import OnlyRuntime


@dataclass(frozen=True, slots=True)
class OnlyRuntimeBuildRequest:
    plan: OnlyRuntimePlan
    components: object

    @property
    def config(self) -> OnlyRuntimeAssemblyPlan:
        return self.plan.assembly_plan


@dataclass(frozen=True, slots=True)
class OnlyRuntimeBuildResult:
    runtime: OnlyRuntime | None = None
    failure_code: str | None = None
    failure_message: str | None = None

    @property
    def supported(self) -> bool:
        return self.runtime is not None


class OnlyRuntimeFactory(Protocol):
    @property
    def runtime_type(self) -> str: ...

    def create(self, request: OnlyRuntimeBuildRequest) -> OnlyRuntimeBuildResult: ...


class OnlyRuntimeFactoryRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, OnlyRuntimeFactory] = {}

    def register(self, factory: OnlyRuntimeFactory) -> None:
        key = factory.runtime_type.upper()
        if key in self._factories:
            raise ValueError(f"duplicate Runtime factory: {key}")
        self._factories[key] = factory

    def require(self, runtime_type: str) -> OnlyRuntimeFactory:
        try:
            return self._factories[runtime_type.upper()]
        except KeyError as exc:
            raise ValueError(f"RUNTIME_FACTORY_NOT_AVAILABLE: {runtime_type}") from exc


class OnlyUnsupportedRuntimeFactory:
    def __init__(self, runtime_type: str) -> None:
        self._runtime_type = runtime_type.upper()

    @property
    def runtime_type(self) -> str:
        return self._runtime_type

    def create(self, request: OnlyRuntimeBuildRequest) -> OnlyRuntimeBuildResult:
        del request
        return OnlyRuntimeBuildResult(
            failure_code="UNSUPPORTED_RUNTIME_TYPE",
            failure_message=f"{self.runtime_type} Runtime is registered but not implemented in phase one",
        )
