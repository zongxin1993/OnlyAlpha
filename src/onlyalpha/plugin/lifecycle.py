"""Uniform plugin resource lifecycle, health, and snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol

from onlyalpha.plugin.descriptor import OnlyPluginDescriptor


class OnlyPluginLifecycleState(StrEnum):
    CREATED = "CREATED"
    INITIALIZED = "INITIALIZED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class OnlyPluginHealthStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    STOPPED = "STOPPED"


@dataclass(frozen=True, slots=True)
class OnlyPluginHealth:
    status: OnlyPluginHealthStatus
    message: str | None = None
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    details: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))


class OnlyPluginResource(Protocol):
    @property
    def plugin_descriptor(self) -> OnlyPluginDescriptor: ...

    @property
    def plugin_resource_id(self) -> str: ...

    @property
    def state(self) -> OnlyPluginLifecycleState: ...

    def initialize(self) -> None: ...

    def connect(self) -> object: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...

    def health(self) -> OnlyPluginHealth: ...


@dataclass(frozen=True, slots=True)
class OnlyPluginResourceSnapshot:
    plugin_id: str
    plugin_type: str
    resource_id: str
    state: OnlyPluginLifecycleState
    health: OnlyPluginHealth
    capabilities: object
    reference_count: int
