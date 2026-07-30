"""The sole business writer to one Runtime EventBus."""

from __future__ import annotations

from onlyalpha.event.bus import OnlyEventBus, OnlyEventScopeError
from onlyalpha.event.model import OnlyEvent, OnlyEventScope
from onlyalpha.event.ports import (
    OnlyRuntimeEventDisposition,
    OnlyRuntimeEventPublicationResult,
    OnlyRuntimeEventRoute,
)
from onlyalpha.runtime.events.gate import (
    OnlyRuntimeEventGateError,
    OnlyRuntimeEventGateSnapshot,
    OnlyRuntimeEventRouteError,
    OnlyRuntimeRecoveryEventGate,
)


class OnlyRuntimeEventRouter:
    def __init__(
        self, event_bus: OnlyEventBus, gate: OnlyRuntimeRecoveryEventGate, runtime_scope: OnlyEventScope
    ) -> None:
        self._event_bus = event_bus
        self._gate = gate
        self._runtime_scope = runtime_scope

    def publish_direct(self, event: OnlyEvent) -> OnlyRuntimeEventPublicationResult:
        return self.publish_direct_many((event,))

    def publish_direct_many(self, events: tuple[OnlyEvent, ...]) -> OnlyRuntimeEventPublicationResult:
        return self._publish(OnlyRuntimeEventRoute.EXTERNAL_DIRECT, events)

    def publish_durable(self, event: OnlyEvent) -> OnlyRuntimeEventPublicationResult:
        return self._publish(OnlyRuntimeEventRoute.DURABLE_OUTBOX, (event,))

    def publish_lifecycle(self, event: OnlyEvent) -> OnlyRuntimeEventPublicationResult:
        return self._publish(OnlyRuntimeEventRoute.LIFECYCLE, (event,))

    def begin_recovery(self) -> int:
        return self._gate.begin_recovery()

    def begin_finalization(self) -> None:
        self._gate.begin_finalization()

    def complete_fresh_bootstrap(self) -> None:
        self._gate.complete_fresh_bootstrap()

    def complete_recovery(self) -> None:
        self._gate.complete_recovery()

    def open(self) -> OnlyRuntimeEventPublicationResult:
        staged = self._gate.open()
        try:
            published = self._event_bus.publish_many_atomic(staged)
        except Exception:
            self._gate.fail()
            raise
        self._gate.record_published(OnlyRuntimeEventRoute.EXTERNAL_DIRECT, published)
        return OnlyRuntimeEventPublicationResult(
            OnlyRuntimeEventRoute.EXTERNAL_DIRECT,
            OnlyRuntimeEventDisposition.PUBLISHED,
            len(staged),
            published,
            0,
            0,
            0,
        )

    def fail(self) -> None:
        self._gate.fail()

    def close(self) -> None:
        self._gate.close()

    def snapshot(self) -> OnlyRuntimeEventGateSnapshot:
        return self._gate.snapshot()

    def _publish(
        self, route: OnlyRuntimeEventRoute, events: tuple[OnlyEvent, ...]
    ) -> OnlyRuntimeEventPublicationResult:
        for event in events:
            if not self._runtime_scope.includes(event.scope):
                raise OnlyEventScopeError(
                    f"event scope {event.scope} does not belong to Runtime scope {self._runtime_scope}"
                )
        decision = self._gate.stage_or_route(route, events)
        result = decision.result
        if result.disposition is OnlyRuntimeEventDisposition.REJECTED:
            raise OnlyRuntimeEventGateError("RUNTIME_EVENT_GATE_ROUTE_REJECTED", result.error or "event route rejected")
        if result.disposition is not OnlyRuntimeEventDisposition.PUBLISHED:
            return result
        published = 0
        try:
            for event in decision.events_to_publish:
                if not self._event_bus.publish(event):
                    raise OnlyRuntimeEventRouteError("RUNTIME_EVENT_BUS_REJECTED", "EventBus rejected event")
                published += 1
        except Exception:
            self._gate.fail()
            raise
        self._gate.record_published(route, published)
        return result


__all__ = ["OnlyRuntimeEventRouter"]
