"""PRIMARY_ONLY strategy dispatch after an explicit ready barrier."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.cluster.bar_context import OnlyBarContext
from onlyalpha.cluster.base import OnlyCluster
from onlyalpha.cluster.manager import OnlyClusterExecutionResult, OnlyClusterFailure
from onlyalpha.core.clock import OnlyClockView
from onlyalpha.domain.identifiers import OnlyClusterId
from onlyalpha.domain.market import OnlyBar
from onlyalpha.indicator.base import OnlyIndicatorId
from onlyalpha.market_data.pipeline import OnlyMarketDataPipeline, OnlyMarketDataUpdateResult
from onlyalpha.market_data.snapshot import OnlyMarketDataSnapshotError
from onlyalpha.market_data.subscriptions import OnlyBarSubscription


@dataclass(frozen=True, slots=True)
class OnlyClusterBarSubscription:
    cluster: OnlyCluster
    subscription: OnlyBarSubscription
    indicator_ids: tuple[OnlyIndicatorId, ...] = ()


@dataclass(frozen=True, slots=True)
class OnlyBarDispatchPlan:
    cluster_id: OnlyClusterId
    cluster: OnlyCluster
    subscription: OnlyBarSubscription
    indicator_ids: tuple[OnlyIndicatorId, ...]


@dataclass(frozen=True, slots=True)
class OnlyBarDispatchResult:
    cluster_id: OnlyClusterId
    ts_event_ns: int
    called: bool
    succeeded: bool
    primary_bar: OnlyBar | None
    error_message: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "cluster_id": str(self.cluster_id),
            "ts_event_ns": self.ts_event_ns,
            "called": self.called,
            "succeeded": self.succeeded,
            "primary_bar": None if self.primary_bar is None else self.primary_bar.to_dict(),
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> OnlyBarDispatchResult:
        primary_payload = payload.get("primary_bar")
        if primary_payload is not None and not isinstance(primary_payload, dict):
            raise ValueError("primary_bar must be a mapping or null")
        return cls(
            cluster_id=OnlyClusterId(str(payload["cluster_id"])),
            ts_event_ns=int(str(payload["ts_event_ns"])),
            called=bool(payload["called"]),
            succeeded=bool(payload["succeeded"]),
            primary_bar=None if primary_payload is None else OnlyBar.from_dict(primary_payload),
            error_message=None if payload.get("error_message") is None else str(payload["error_message"]),
        )


class OnlyBarDispatchExecutor(Protocol):
    """Execution boundary implemented by ClusterManager in a Runtime."""

    def execute_bar(
        self,
        cluster_id: OnlyClusterId,
        cluster: OnlyCluster,
        bar: OnlyBar,
        snapshot: object,
    ) -> OnlyClusterExecutionResult: ...


class OnlyDirectBarDispatchExecutor:
    """Compatibility executor for isolated Dispatcher component tests and demos."""

    def __init__(self, clock_view: OnlyClockView) -> None:
        self._clock_view = clock_view

    def execute_bar(
        self,
        cluster_id: OnlyClusterId,
        cluster: OnlyCluster,
        bar: OnlyBar,
        snapshot: object,
    ) -> OnlyClusterExecutionResult:
        from onlyalpha.market_data.snapshot import OnlyMarketDataSnapshot

        assert isinstance(snapshot, OnlyMarketDataSnapshot)
        try:
            cluster.on_bar(bar, OnlyBarContext(snapshot, self._clock_view))
        except Exception as exc:
            failure = OnlyClusterFailure(
                snapshot.runtime_id,
                cluster_id,
                "on_bar",
                type(exc).__name__,
                str(exc),
                snapshot.ts_event.unix_nanos,
                bar.bar_type.to_json(),
            )
            return OnlyClusterExecutionResult(cluster_id, "on_bar", True, False, failure)
        return OnlyClusterExecutionResult(cluster_id, "on_bar", True, True)


class OnlyStrategyBarDispatcher:
    """Stable Cluster iteration; business readiness comes only from Pipeline result."""

    def __init__(
        self,
        pipeline: OnlyMarketDataPipeline,
        clock_view: OnlyClockView,
        executor: OnlyBarDispatchExecutor | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._executor = OnlyDirectBarDispatchExecutor(clock_view) if executor is None else executor
        self._plans: dict[OnlyClusterId, OnlyBarDispatchPlan] = {}
        self._handled_slices: set[tuple[OnlyClusterId, int]] = set()

    def register(self, registration: OnlyClusterBarSubscription) -> None:
        cluster_id = OnlyClusterId(registration.cluster.config.cluster_id)
        if cluster_id in self._plans:
            raise ValueError(f"Cluster Bar subscription already registered: {cluster_id}")
        self._pipeline.register_subscription(registration.subscription)
        self._plans[cluster_id] = OnlyBarDispatchPlan(
            cluster_id,
            registration.cluster,
            registration.subscription,
            tuple(sorted(set(registration.indicator_ids))),
        )

    def unregister(self, cluster_id: OnlyClusterId) -> bool:
        plan = self._plans.pop(cluster_id, None)
        if plan is None:
            return False
        self._pipeline.unregister_subscription(plan.subscription)
        self._handled_slices = {item for item in self._handled_slices if item[0] != cluster_id}
        return True

    @property
    def subscription_count(self) -> int:
        return len(self._plans)

    def dispatch(self, update: OnlyMarketDataUpdateResult) -> tuple[OnlyBarDispatchResult, ...]:
        update.barrier.require_ready()
        results: list[OnlyBarDispatchResult] = []
        for cluster_id in sorted(self._plans, key=str):
            plan = self._plans[cluster_id]
            primary_bar_type = plan.subscription.primary_bar_type
            assert primary_bar_type is not None
            event_ns = update.snapshot.ts_event.unix_nanos
            if primary_bar_type not in update.updated_bar_types:
                results.append(OnlyBarDispatchResult(cluster_id, event_ns, False, True, None))
                continue
            slice_key = (cluster_id, event_ns)
            if slice_key in self._handled_slices:
                raise ValueError(f"Cluster already handled logical time slice: {cluster_id} {event_ns}")
            self._handled_slices.add(slice_key)
            try:
                snapshot = update.snapshot.restrict(
                    cluster_id=cluster_id,
                    bar_types=plan.subscription.bar_types,
                    primary_bar_type=primary_bar_type,
                    indicator_ids=plan.indicator_ids,
                )
                execution = self._executor.execute_bar(
                    cluster_id,
                    plan.cluster,
                    snapshot.primary_bar,
                    snapshot,
                )
                results.append(
                    OnlyBarDispatchResult(
                        cluster_id,
                        event_ns,
                        execution.called,
                        execution.succeeded,
                        snapshot.primary_bar if execution.called else None,
                        None
                        if execution.failure is None
                        else f"{execution.failure.error_type}: {execution.failure.message}",
                    )
                )
            except Exception as exc:
                if isinstance(exc, OnlyMarketDataSnapshotError):
                    raise
                results.append(
                    OnlyBarDispatchResult(cluster_id, event_ns, True, False, None, f"{type(exc).__name__}: {exc}")
                )
        return tuple(results)
