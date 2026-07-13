"""Top-level lifecycle coordinator."""

from enum import Enum, auto

from onlyalpha.core.errors import OnlyDuplicateIdError, OnlyLifecycleError
from onlyalpha.runtime.runtime import OnlyRuntime
from onlyalpha.storage.base import OnlyStorage


class OnlyEngineState(Enum):
    """Engine lifecycle states for the initial skeleton."""

    CREATED = auto()
    READY = auto()
    RUNNING = auto()
    STOPPED = auto()


class OnlyEngine:
    """Coordinates runtimes and durable storage without implementing trading logic."""

    def __init__(self, engine_id: str, storage: OnlyStorage | None = None) -> None:
        if not engine_id.strip():
            raise ValueError("engine_id is required")
        self.engine_id = engine_id
        self.storage = storage
        self.state = OnlyEngineState.CREATED
        self._runtimes: dict[str, OnlyRuntime] = {}

    @property
    def runtimes(self) -> tuple[OnlyRuntime, ...]:
        return tuple(self._runtimes.values())

    def register_runtime(self, runtime: OnlyRuntime) -> None:
        if self.state is not OnlyEngineState.CREATED:
            raise OnlyLifecycleError("runtimes must be registered before initialization")
        if runtime.runtime_id in self._runtimes:
            raise OnlyDuplicateIdError(f"runtime already registered: {runtime.runtime_id}")
        self._runtimes[runtime.runtime_id] = runtime

    def initialize(self) -> None:
        if self.state is not OnlyEngineState.CREATED:
            raise OnlyLifecycleError("engine can only initialize from CREATED")
        self.state = OnlyEngineState.READY

    def start(self) -> None:
        if self.state is not OnlyEngineState.READY:
            raise OnlyLifecycleError("engine can only start from READY")
        self.state = OnlyEngineState.RUNNING
        for runtime in self._runtimes.values():
            runtime.start()

    def stop(self) -> None:
        if self.state is OnlyEngineState.STOPPED:
            return
        for runtime in reversed(tuple(self._runtimes.values())):
            runtime.stop()
        if self.storage is not None:
            self.storage.close()
        self.state = OnlyEngineState.STOPPED
