"""Cluster lifecycle and runtime-facing context."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum, auto
from types import MappingProxyType

from onlyalpha.cache.base import OnlyCache
from onlyalpha.core.clock import OnlyClockView
from onlyalpha.core.errors import OnlyLifecycleError
from onlyalpha.event.bus import OnlyEventBus


class OnlyClusterState(Enum):
    """Minimal cluster lifecycle states."""

    CREATED = auto()
    INITIALIZED = auto()
    RUNNING = auto()
    STOPPED = auto()
    FAILED = auto()


@dataclass(frozen=True, slots=True)
class OnlyClusterConfig:
    """Immutable cluster identity and user configuration."""

    cluster_id: str
    values: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.cluster_id.strip():
            raise ValueError("cluster_id is required")
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))


@dataclass(frozen=True, slots=True)
class OnlyClusterContext:
    """Narrow set of runtime services available to a cluster."""

    engine_id: str
    runtime_id: str
    cluster_id: str
    clock: OnlyClockView
    event_bus: OnlyEventBus
    cache: OnlyCache


class OnlyCluster:
    """Isolated strategy lifecycle unit without gateway or storage access."""

    def __init__(self, config: OnlyClusterConfig) -> None:
        self.config = config
        self.context: OnlyClusterContext | None = None
        self.state = OnlyClusterState.CREATED

    def initialize(self, context: OnlyClusterContext) -> None:
        if self.state is not OnlyClusterState.CREATED:
            raise OnlyLifecycleError("cluster can only initialize from CREATED")
        if context.cluster_id != self.config.cluster_id:
            raise ValueError("cluster context identity mismatch")
        self.context = context
        self.on_initialize()
        self.state = OnlyClusterState.INITIALIZED

    def start(self) -> None:
        if self.state is not OnlyClusterState.INITIALIZED:
            raise OnlyLifecycleError("cluster can only start from INITIALIZED")
        try:
            self.on_start()
            self.state = OnlyClusterState.RUNNING
        except Exception:
            self.state = OnlyClusterState.FAILED
            raise

    def stop(self) -> None:
        if self.state in {OnlyClusterState.STOPPED, OnlyClusterState.CREATED}:
            self.state = OnlyClusterState.STOPPED
            return
        try:
            self.on_stop()
        finally:
            self.state = OnlyClusterState.STOPPED

    def on_initialize(self) -> None:
        """Initialize cluster-owned resources."""

    def on_start(self) -> None:
        """Begin cluster work."""

    def on_stop(self) -> None:
        """Stop cluster work idempotently."""
