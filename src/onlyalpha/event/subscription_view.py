"""Read-only subscription facade over a Runtime-owned EventBus."""

from __future__ import annotations

from onlyalpha.event.bus import (
    OnlyDroppedEvent,
    OnlyEventBus,
    OnlyEventDispatchResult,
    OnlyEventFailure,
    OnlyEventHandler,
    OnlySubscription,
    OnlySubscriptionId,
)
from onlyalpha.event.model import OnlyEventPriority, OnlyEventType


class OnlyEventBusSubscriptionView:
    def __init__(self, event_bus: OnlyEventBus) -> None:
        self._event_bus = event_bus

    @property
    def failures(self) -> tuple[OnlyEventFailure, ...]:
        return self._event_bus.failures

    @property
    def dispatch_results(self) -> tuple[OnlyEventDispatchResult, ...]:
        return self._event_bus.dispatch_results

    @property
    def dropped_events(self) -> tuple[OnlyDroppedEvent, ...]:
        return self._event_bus.dropped_events

    def pending_count(self) -> int:
        return self._event_bus.pending_count()

    def subscribe(
        self,
        event_type: OnlyEventType | str,
        handler: OnlyEventHandler,
        *,
        priority: OnlyEventPriority = OnlyEventPriority.NORMAL,
    ) -> OnlySubscription:
        return self._event_bus.subscribe(event_type, handler, priority=priority)

    def unsubscribe(self, subscription_id: OnlySubscriptionId) -> bool:
        return self._event_bus.unsubscribe(subscription_id)


__all__ = ["OnlyEventBusSubscriptionView"]
