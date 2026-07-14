"""Manager-owned Cluster lifecycle, callback execution and failure isolation."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from onlyalpha.cluster.bar_context import OnlyBarContext
from onlyalpha.cluster.base import OnlyCluster, OnlyClusterError, OnlyClusterState
from onlyalpha.core.clock import OnlyTimerEvent
from onlyalpha.core.errors import OnlyDuplicateIdError, OnlyLifecycleError, OnlyNotFoundError
from onlyalpha.domain.identifiers import OnlyClusterId, OnlyRuntimeId
from onlyalpha.domain.market import OnlyBar
from onlyalpha.market_data.snapshot import OnlyMarketDataSnapshot
from onlyalpha.runtime.context import OnlyClusterContext, OnlyTimerContext

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OnlyClusterFailure:
    runtime_id: OnlyRuntimeId
    cluster_id: OnlyClusterId
    callback: str
    error_type: str
    message: str
    ts_event_ns: int | None = None
    bar_type: str | None = None


@dataclass(frozen=True, slots=True)
class OnlyClusterExecutionResult:
    cluster_id: OnlyClusterId
    callback: str
    called: bool
    succeeded: bool
    failure: OnlyClusterFailure | None = None


@dataclass(frozen=True, slots=True)
class OnlyClusterStatus:
    cluster_id: OnlyClusterId
    state: OnlyClusterState
    last_failure: OnlyClusterFailure | None


@dataclass(slots=True)
class OnlyManagedCluster:
    cluster: OnlyCluster
    state: OnlyClusterState
    context: OnlyClusterContext | None = None
    last_failure: OnlyClusterFailure | None = None


class OnlyClusterManager:
    """Unique lifecycle truth and serial execution boundary for one Runtime."""

    def __init__(
        self,
        runtime_id: OnlyRuntimeId,
        context_factory: Callable[[OnlyClusterId], OnlyClusterContext],
        cleanup: Callable[[OnlyClusterId], None],
    ) -> None:
        self._runtime_id = runtime_id
        self._context_factory = context_factory
        self._cleanup = cleanup
        self._clusters: dict[OnlyClusterId, OnlyManagedCluster] = {}

    @property
    def clusters(self) -> tuple[OnlyCluster, ...]:
        return tuple(self._clusters[key].cluster for key in sorted(self._clusters, key=str))

    def register(self, cluster: OnlyCluster) -> None:
        cluster_id = OnlyClusterId(cluster.config.cluster_id)
        if cluster_id in self._clusters:
            raise OnlyDuplicateIdError(f"cluster already exists in runtime: {cluster_id}")
        managed = OnlyManagedCluster(cluster, OnlyClusterState.CREATED)
        self._clusters[cluster_id] = managed
        context = self._context_factory(cluster_id)
        managed.context = context
        cluster._only_manager_bind(context)
        try:
            cluster.on_load()
        except Exception as exc:
            self._fail(managed, cluster_id, "on_load", exc)
            raise OnlyClusterError(f"Cluster load failed: {cluster_id}") from exc
        self._transition(managed, OnlyClusterState.LOADED)

    def initialize_all(self) -> None:
        for cluster_id in sorted(self._clusters, key=str):
            managed = self._clusters[cluster_id]
            self._require_state(managed, {OnlyClusterState.LOADED}, "initialize")
            try:
                managed.cluster.on_initialize()
            except Exception as exc:
                self._fail(managed, cluster_id, "on_initialize", exc)
                self._cleanup(cluster_id)
                continue
            self._transition(managed, OnlyClusterState.INITIALIZED)

    def start_all(self) -> None:
        for cluster_id in sorted(self._clusters, key=str):
            self.start(cluster_id)

    def start(self, cluster_id: OnlyClusterId) -> None:
        managed = self._require(cluster_id)
        if managed.state is OnlyClusterState.FAILED:
            return
        self._require_state(managed, {OnlyClusterState.INITIALIZED, OnlyClusterState.STOPPED}, "start")
        self._transition(managed, OnlyClusterState.STARTING)
        try:
            managed.cluster.on_start()
        except Exception as exc:
            self._fail(managed, cluster_id, "on_start", exc)
            self._cleanup(cluster_id)
            return
        self._transition(managed, OnlyClusterState.RUNNING)

    def stop_all(self) -> None:
        for cluster_id in reversed(sorted(self._clusters, key=str)):
            self.stop(cluster_id)

    def pause_all(self) -> None:
        for managed in self._clusters.values():
            if managed.state is OnlyClusterState.RUNNING:
                self._transition(managed, OnlyClusterState.PAUSED)

    def resume_all(self) -> None:
        for managed in self._clusters.values():
            if managed.state is OnlyClusterState.PAUSED:
                self._transition(managed, OnlyClusterState.RUNNING)

    def stop(self, cluster_id: OnlyClusterId) -> None:
        managed = self._require(cluster_id)
        if managed.state in {OnlyClusterState.STOPPED, OnlyClusterState.UNLOADED}:
            return
        if managed.state is OnlyClusterState.LOADED:
            self._cleanup(cluster_id)
            self._transition(managed, OnlyClusterState.STOPPED)
            return
        self._require_state(
            managed,
            {
                OnlyClusterState.INITIALIZED,
                OnlyClusterState.RUNNING,
                OnlyClusterState.PAUSED,
                OnlyClusterState.FAILED,
            },
            "stop",
        )
        self._transition(managed, OnlyClusterState.STOPPING)
        try:
            managed.cluster.on_stop()
        except Exception as exc:
            managed.last_failure = self._failure(cluster_id, "on_stop", exc)
        finally:
            self._cleanup(cluster_id)
            self._transition(managed, OnlyClusterState.STOPPED)

    def unload_all(self) -> None:
        for cluster_id in reversed(sorted(self._clusters, key=str)):
            managed = self._clusters[cluster_id]
            if managed.state is not OnlyClusterState.STOPPED:
                self.stop(cluster_id)
            try:
                managed.cluster.on_unload()
            finally:
                self._transition(managed, OnlyClusterState.UNLOADED)

    def execute_bar(
        self,
        cluster_id: OnlyClusterId,
        bar: OnlyBar,
        snapshot: OnlyMarketDataSnapshot,
    ) -> OnlyClusterExecutionResult:
        managed = self._require(cluster_id)
        if managed.state is not OnlyClusterState.RUNNING or managed.context is None:
            return OnlyClusterExecutionResult(cluster_id, "on_bar", False, True)
        try:
            managed.cluster.on_bar(bar, OnlyBarContext(snapshot, managed.context))
        except Exception as exc:
            failure = self._fail(
                managed,
                cluster_id,
                "on_bar",
                exc,
                ts_event_ns=snapshot.ts_event.unix_nanos,
                bar_type=bar.bar_type.to_json(),
            )
            self._cleanup(cluster_id)
            return OnlyClusterExecutionResult(cluster_id, "on_bar", True, False, failure)
        return OnlyClusterExecutionResult(cluster_id, "on_bar", True, True)

    def execute_timer(self, cluster_id: OnlyClusterId, event: OnlyTimerEvent) -> OnlyClusterExecutionResult:
        managed = self._require(cluster_id)
        if managed.state is not OnlyClusterState.RUNNING or managed.context is None:
            return OnlyClusterExecutionResult(cluster_id, "on_timer", False, True)
        try:
            managed.cluster.on_timer(OnlyTimerContext(event, managed.context))
        except Exception as exc:
            failure = self._fail(managed, cluster_id, "on_timer", exc, ts_event_ns=event.deadline_ns)
            self._cleanup(cluster_id)
            return OnlyClusterExecutionResult(cluster_id, "on_timer", True, False, failure)
        return OnlyClusterExecutionResult(cluster_id, "on_timer", True, True)

    def state_of(self, cluster_id: OnlyClusterId) -> OnlyClusterState:
        return self._require(cluster_id).state

    def status(self) -> tuple[OnlyClusterStatus, ...]:
        return tuple(
            OnlyClusterStatus(cluster_id, self._clusters[cluster_id].state, self._clusters[cluster_id].last_failure)
            for cluster_id in sorted(self._clusters, key=str)
        )

    def _fail(
        self,
        managed: OnlyManagedCluster,
        cluster_id: OnlyClusterId,
        callback: str,
        error: Exception,
        *,
        ts_event_ns: int | None = None,
        bar_type: str | None = None,
    ) -> OnlyClusterFailure:
        failure = self._failure(cluster_id, callback, error, ts_event_ns=ts_event_ns, bar_type=bar_type)
        managed.last_failure = failure
        self._transition(managed, OnlyClusterState.FAILED)
        try:
            managed.cluster.on_error(error)
        except Exception as callback_error:
            _LOGGER.exception("Cluster on_error callback failed", exc_info=callback_error)
        return failure

    def _failure(
        self,
        cluster_id: OnlyClusterId,
        callback: str,
        error: Exception,
        *,
        ts_event_ns: int | None = None,
        bar_type: str | None = None,
    ) -> OnlyClusterFailure:
        return OnlyClusterFailure(
            self._runtime_id,
            cluster_id,
            callback,
            type(error).__name__,
            str(error),
            ts_event_ns,
            bar_type,
        )

    def _transition(self, managed: OnlyManagedCluster, state: OnlyClusterState) -> None:
        managed.state = state
        managed.cluster._only_manager_transition(state)

    def _require(self, cluster_id: OnlyClusterId) -> OnlyManagedCluster:
        try:
            return self._clusters[cluster_id]
        except KeyError as exc:
            raise OnlyNotFoundError(f"unknown cluster: {cluster_id}") from exc

    @staticmethod
    def _require_state(
        managed: OnlyManagedCluster,
        allowed: set[OnlyClusterState],
        action: str,
    ) -> None:
        if managed.state not in allowed:
            raise OnlyLifecycleError(f"cannot {action} Cluster from {managed.state.value}")
