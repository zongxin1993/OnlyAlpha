"""Pure recovery-aware state machine for externally observable Runtime events."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.core.errors import OnlyLifecycleError
from onlyalpha.event.model import OnlyEvent
from onlyalpha.event.ports import (
    OnlyRuntimeEventDisposition,
    OnlyRuntimeEventPublicationResult,
    OnlyRuntimeEventRoute,
)


class OnlyRuntimeEventGatePhase(StrEnum):
    BOOTSTRAPPING = "BOOTSTRAPPING"
    RECOVERING = "RECOVERING"
    FINALIZING = "FINALIZING"
    READY_BLOCKED = "READY_BLOCKED"
    OPEN = "OPEN"
    FAILED = "FAILED"
    CLOSED = "CLOSED"


class OnlyRuntimeEventGateError(OnlyLifecycleError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class OnlyRuntimeEventGateTransitionError(OnlyRuntimeEventGateError):
    pass


class OnlyRuntimeEventStageCapacityError(OnlyRuntimeEventGateError):
    pass


class OnlyRuntimeEventRouteError(OnlyRuntimeEventGateError):
    pass


@dataclass(frozen=True, slots=True)
class OnlySuppressedRuntimeEvent:
    event_type: str
    source: str
    sequence: int
    timestamp_ns: int
    route: OnlyRuntimeEventRoute
    phase: OnlyRuntimeEventGatePhase
    reason: str


@dataclass(frozen=True, slots=True)
class OnlyRuntimeEventGateSnapshot:
    phase: OnlyRuntimeEventGatePhase
    staged_count: int
    published_direct_count: int
    published_durable_count: int
    published_lifecycle_count: int
    suppressed_direct_count: int
    rejected_count: int
    discarded_bootstrap_count: int
    last_suppressed_events: tuple[OnlySuppressedRuntimeEvent, ...]


@dataclass(frozen=True, slots=True)
class OnlyRuntimeEventGateDecision:
    result: OnlyRuntimeEventPublicationResult
    events_to_publish: tuple[OnlyEvent, ...] = ()


class OnlyRuntimeRecoveryEventGate:
    def __init__(self, staging_capacity: int, *, suppressed_sample_capacity: int = 16) -> None:
        if staging_capacity <= 0:
            raise ValueError("Runtime event staging capacity must be positive")
        if suppressed_sample_capacity <= 0:
            raise ValueError("suppressed event sample capacity must be positive")
        self._staging_capacity = staging_capacity
        self._phase = OnlyRuntimeEventGatePhase.BOOTSTRAPPING
        self._staged: deque[OnlyEvent] = deque()
        self._suppressed_samples: deque[OnlySuppressedRuntimeEvent] = deque(maxlen=suppressed_sample_capacity)
        self._published_direct_count = 0
        self._published_durable_count = 0
        self._published_lifecycle_count = 0
        self._suppressed_direct_count = 0
        self._rejected_count = 0
        self._discarded_bootstrap_count = 0

    @property
    def phase(self) -> OnlyRuntimeEventGatePhase:
        return self._phase

    def stage_or_route(
        self, route: OnlyRuntimeEventRoute, events: tuple[OnlyEvent, ...]
    ) -> OnlyRuntimeEventGateDecision:
        attempted = len(events)
        if not events:
            disposition = (
                OnlyRuntimeEventDisposition.PUBLISHED
                if self._phase is OnlyRuntimeEventGatePhase.OPEN
                else OnlyRuntimeEventDisposition.STAGED
                if route is OnlyRuntimeEventRoute.EXTERNAL_DIRECT
                and self._phase in {OnlyRuntimeEventGatePhase.BOOTSTRAPPING, OnlyRuntimeEventGatePhase.READY_BLOCKED}
                else OnlyRuntimeEventDisposition.SUPPRESSED
                if route is OnlyRuntimeEventRoute.EXTERNAL_DIRECT
                and self._phase in {OnlyRuntimeEventGatePhase.RECOVERING, OnlyRuntimeEventGatePhase.FINALIZING}
                else OnlyRuntimeEventDisposition.REJECTED
            )
            return OnlyRuntimeEventGateDecision(self._result(route, disposition, 0))
        if self._phase is OnlyRuntimeEventGatePhase.OPEN:
            return OnlyRuntimeEventGateDecision(
                self._result(route, OnlyRuntimeEventDisposition.PUBLISHED, attempted, published=attempted), events
            )
        if route is OnlyRuntimeEventRoute.EXTERNAL_DIRECT:
            if self._phase in {OnlyRuntimeEventGatePhase.BOOTSTRAPPING, OnlyRuntimeEventGatePhase.READY_BLOCKED}:
                if len(self._staged) + attempted > self._staging_capacity:
                    self._phase = OnlyRuntimeEventGatePhase.FAILED
                    self._staged.clear()
                    raise OnlyRuntimeEventStageCapacityError(
                        "RUNTIME_EVENT_STAGE_CAPACITY_EXCEEDED",
                        f"staging {attempted} events exceeds capacity {self._staging_capacity}",
                    )
                self._staged.extend(events)
                return OnlyRuntimeEventGateDecision(
                    self._result(route, OnlyRuntimeEventDisposition.STAGED, attempted, staged=attempted)
                )
            if self._phase in {OnlyRuntimeEventGatePhase.RECOVERING, OnlyRuntimeEventGatePhase.FINALIZING}:
                self._suppressed_direct_count += attempted
                for event in events:
                    self._suppressed_samples.append(
                        OnlySuppressedRuntimeEvent(
                            str(event.event_type),
                            str(event.source),
                            int(event.sequence),
                            0 if event.timestamp_ns is None else event.timestamp_ns,
                            route,
                            self._phase,
                            "historical direct event suppressed during recovery",
                        )
                    )
                return OnlyRuntimeEventGateDecision(
                    self._result(route, OnlyRuntimeEventDisposition.SUPPRESSED, attempted, suppressed=attempted)
                )
        self._rejected_count += attempted
        return OnlyRuntimeEventGateDecision(
            self._result(
                route,
                OnlyRuntimeEventDisposition.REJECTED,
                attempted,
                rejected=attempted,
                error=f"route {route.value} is rejected while gate is {self._phase.value}",
            )
        )

    def begin_recovery(self) -> int:
        self._transition(OnlyRuntimeEventGatePhase.BOOTSTRAPPING, OnlyRuntimeEventGatePhase.RECOVERING)
        discarded = len(self._staged)
        self._discarded_bootstrap_count += discarded
        self._staged.clear()
        return discarded

    def begin_finalization(self) -> None:
        self._transition(OnlyRuntimeEventGatePhase.RECOVERING, OnlyRuntimeEventGatePhase.FINALIZING)

    def complete_fresh_bootstrap(self) -> None:
        self._transition(OnlyRuntimeEventGatePhase.BOOTSTRAPPING, OnlyRuntimeEventGatePhase.READY_BLOCKED)

    def complete_recovery(self) -> None:
        self._transition(OnlyRuntimeEventGatePhase.FINALIZING, OnlyRuntimeEventGatePhase.READY_BLOCKED)
        if self._staged:
            self._phase = OnlyRuntimeEventGatePhase.FAILED
            self._staged.clear()
            raise OnlyRuntimeEventGateError(
                "RUNTIME_EVENT_RECOVERY_STAGING_NOT_EMPTY", "recovery completion requires empty staging"
            )

    def open(self) -> tuple[OnlyEvent, ...]:
        self._transition(OnlyRuntimeEventGatePhase.READY_BLOCKED, OnlyRuntimeEventGatePhase.OPEN)
        staged = tuple(self._staged)
        self._staged.clear()
        return staged

    def fail(self) -> None:
        if self._phase is OnlyRuntimeEventGatePhase.CLOSED:
            return
        self._phase = OnlyRuntimeEventGatePhase.FAILED
        self._staged.clear()

    def close(self) -> None:
        if self._phase is OnlyRuntimeEventGatePhase.CLOSED:
            return
        if self._phase not in {OnlyRuntimeEventGatePhase.OPEN, OnlyRuntimeEventGatePhase.FAILED}:
            raise OnlyRuntimeEventGateTransitionError(
                "RUNTIME_EVENT_GATE_ILLEGAL_TRANSITION", f"cannot close from {self._phase.value}"
            )
        self._phase = OnlyRuntimeEventGatePhase.CLOSED
        self._staged.clear()

    def record_published(self, route: OnlyRuntimeEventRoute, count: int) -> None:
        if route is OnlyRuntimeEventRoute.EXTERNAL_DIRECT:
            self._published_direct_count += count
        elif route is OnlyRuntimeEventRoute.DURABLE_OUTBOX:
            self._published_durable_count += count
        else:
            self._published_lifecycle_count += count

    def snapshot(self) -> OnlyRuntimeEventGateSnapshot:
        return OnlyRuntimeEventGateSnapshot(
            self._phase,
            len(self._staged),
            self._published_direct_count,
            self._published_durable_count,
            self._published_lifecycle_count,
            self._suppressed_direct_count,
            self._rejected_count,
            self._discarded_bootstrap_count,
            tuple(self._suppressed_samples),
        )

    def _transition(self, expected: OnlyRuntimeEventGatePhase, target: OnlyRuntimeEventGatePhase) -> None:
        if self._phase is not expected:
            raise OnlyRuntimeEventGateTransitionError(
                "RUNTIME_EVENT_GATE_ILLEGAL_TRANSITION",
                f"cannot transition {self._phase.value} to {target.value}; expected {expected.value}",
            )
        self._phase = target

    @staticmethod
    def _result(
        route: OnlyRuntimeEventRoute,
        disposition: OnlyRuntimeEventDisposition,
        attempted: int,
        *,
        published: int = 0,
        staged: int = 0,
        suppressed: int = 0,
        rejected: int = 0,
        error: str | None = None,
    ) -> OnlyRuntimeEventPublicationResult:
        return OnlyRuntimeEventPublicationResult(
            route, disposition, attempted, published, staged, suppressed, rejected, error
        )


__all__ = [
    "OnlyRuntimeEventGateDecision",
    "OnlyRuntimeEventGateError",
    "OnlyRuntimeEventGatePhase",
    "OnlyRuntimeEventGateSnapshot",
    "OnlyRuntimeEventGateTransitionError",
    "OnlyRuntimeEventRouteError",
    "OnlyRuntimeEventStageCapacityError",
    "OnlyRuntimeRecoveryEventGate",
    "OnlySuppressedRuntimeEvent",
]
