"""Cluster strategy API; lifecycle mutation belongs to OnlyClusterManager."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from onlyalpha.cluster.bar_context import OnlyBarContext
from onlyalpha.domain.market import OnlyBar
from onlyalpha.runtime.context import OnlyClusterContext as OnlyClusterContext
from onlyalpha.runtime.context import OnlyTimerContext


class OnlyClusterError(Exception):
    """Base Cluster lifecycle or callback error."""


class OnlyClusterState(StrEnum):
    CREATED = "CREATED"
    LOADED = "LOADED"
    INITIALIZED = "INITIALIZED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"
    UNLOADED = "UNLOADED"


@dataclass(frozen=True, slots=True)
class OnlyClusterConfig:
    """Immutable Cluster identity and user configuration."""

    cluster_id: str
    values: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.cluster_id.strip():
            raise ValueError("cluster_id is required")
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))


class OnlyCluster:
    """Isolated strategy unit; Manager alone invokes lifecycle transition hooks."""

    def __init__(self, config: OnlyClusterConfig) -> None:
        self.config = config
        self.__context: OnlyClusterContext | None = None
        self.__state = OnlyClusterState.CREATED

    @property
    def context(self) -> OnlyClusterContext | None:
        return self.__context

    @property
    def state(self) -> OnlyClusterState:
        return self.__state

    def _only_manager_bind(self, context: OnlyClusterContext) -> None:
        self.__context = context

    def _only_manager_transition(self, state: OnlyClusterState) -> None:
        self.__state = state

    def on_load(self) -> None:
        """Allocate Cluster-owned, non-Runtime resources."""

    def on_initialize(self) -> None:
        """Declare subscriptions and timers through the restricted Context."""

    def on_start(self) -> None:
        """Begin Cluster work."""

    def on_bar(self, bar: OnlyBar, context: OnlyBarContext) -> None:
        """Handle one fully prepared primary Bar and immutable Snapshot."""

    def on_timer(self, context: OnlyTimerContext) -> None:
        """Handle one Runtime-owned deterministic Timer firing."""

    def on_stop(self) -> None:
        """Stop Cluster-owned work."""

    def on_unload(self) -> None:
        """Release Cluster-owned resources."""

    def on_error(self, error: Exception) -> None:
        """Observe a callback error after Manager has recorded it."""
