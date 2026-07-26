"""Execution-local event buffering and explicit direct delivery."""

from __future__ import annotations

from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.event.model import OnlyEvent


class OnlyExecutionEventBuffer:
    """Buffers Manager facts; it never publishes to an EventBus."""

    def __init__(self, lifecycle_event_bus: OnlyEventBus) -> None:
        self._lifecycle_event_bus = lifecycle_event_bus
        self._active = False
        self._buffer: list[OnlyEvent] = []

    def begin(self) -> None:
        if self._active:
            raise RuntimeError("nested Execution event buffer is not supported")
        self._active = True
        self._buffer = []

    def publish(self, event: OnlyEvent) -> None:
        if self._active:
            self._buffer.append(event)
        else:
            self._lifecycle_event_bus.publish(event)

    def publish_many(self, events: tuple[OnlyEvent, ...]) -> None:
        if self._active:
            self._buffer.extend(events)
        else:
            self._lifecycle_event_bus.publish_many(events)

    def snapshot(self) -> tuple[OnlyEvent, ...]:
        if not self._active:
            raise RuntimeError("Execution event buffer is not active")
        return tuple(self._buffer)

    def drain(self) -> tuple[OnlyEvent, ...]:
        events = self.snapshot()
        self._active = False
        self._buffer = []
        return events

    def discard(self) -> tuple[OnlyEvent, ...]:
        discarded = tuple(self._buffer)
        self._active = False
        self._buffer = []
        return discarded


class OnlyDirectExecutionEventPublisher:
    """The direct EventBus boundary for successful non-Trade updates only."""

    def __init__(self, event_bus: OnlyEventBus) -> None:
        self._event_bus = event_bus

    def publish_many(self, events: tuple[OnlyEvent, ...]) -> None:
        self._event_bus.publish_many(events)


__all__ = ["OnlyDirectExecutionEventPublisher", "OnlyExecutionEventBuffer"]
