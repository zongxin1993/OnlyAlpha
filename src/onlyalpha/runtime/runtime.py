"""Runtime isolation and lifecycle coordination."""

from enum import Enum, auto

from onlyalpha.cache.base import OnlyCache
from onlyalpha.cluster.base import OnlyCluster, OnlyClusterContext
from onlyalpha.core.clock import OnlyClock
from onlyalpha.core.errors import OnlyDuplicateIdError, OnlyLifecycleError
from onlyalpha.event.bus import OnlyEventBus


class OnlyRuntimeState(Enum):
    """Runtime lifecycle states."""

    CREATED = auto()
    RUNNING = auto()
    STOPPED = auto()


class OnlyRuntime:
    """Owns an isolated clock, event stream, cache namespace and clusters."""

    def __init__(self, runtime_id: str, clock: OnlyClock, event_bus: OnlyEventBus, cache: OnlyCache) -> None:
        if not runtime_id.strip():
            raise ValueError("runtime_id is required")
        self.runtime_id = runtime_id
        self.clock = clock
        self.event_bus = event_bus
        self.cache = cache
        self.state = OnlyRuntimeState.CREATED
        self._clusters: dict[str, OnlyCluster] = {}

    @property
    def clusters(self) -> tuple[OnlyCluster, ...]:
        return tuple(self._clusters.values())

    def add_cluster(self, engine_id: str, cluster: OnlyCluster) -> None:
        cluster_id = cluster.config.cluster_id
        if cluster_id in self._clusters:
            raise OnlyDuplicateIdError(f"cluster already exists in runtime: {cluster_id}")
        cluster.initialize(
            OnlyClusterContext(engine_id, self.runtime_id, cluster_id, self.clock, self.event_bus, self.cache)
        )
        self._clusters[cluster_id] = cluster

    def start(self) -> None:
        if self.state is not OnlyRuntimeState.CREATED:
            raise OnlyLifecycleError("runtime can only start from CREATED")
        self.state = OnlyRuntimeState.RUNNING
        for cluster in self._clusters.values():
            try:
                cluster.start()
            except Exception:
                continue

    def stop(self) -> None:
        if self.state is OnlyRuntimeState.STOPPED:
            return
        for cluster in reversed(tuple(self._clusters.values())):
            cluster.stop()
        self.event_bus.close()
        self.state = OnlyRuntimeState.STOPPED


class OnlyLiveRuntime(OnlyRuntime):
    """Live runtime marker; no real gateway exists in this phase."""


class OnlyPaperRuntime(OnlyRuntime):
    """Paper runtime marker; no matching engine exists in this phase."""


class OnlyBacktestRuntime(OnlyRuntime):
    """Backtest runtime marker driven by an OnlyBacktestClock."""


class OnlyResearchRuntime(OnlyRuntime):
    """Research runtime marker which does not create trading state."""
