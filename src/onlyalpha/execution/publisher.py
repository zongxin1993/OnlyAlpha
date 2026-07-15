"""Transactional fact buffer used by one Runtime Execution Processor."""

from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.event.model import OnlyEvent


class OnlyExecutionEventPublisher:
    """Buffers Manager facts until a complete cross-component update commits."""

    def __init__(self, event_bus: OnlyEventBus) -> None:
        self._event_bus = event_bus
        self._active = False
        self._buffer: list[OnlyEvent] = []

    def begin(self) -> None:
        if self._active:
            raise RuntimeError("nested Execution event transaction is not supported")
        self._active = True
        self._buffer = []

    def publish(self, event: OnlyEvent) -> None:
        if self._active:
            self._buffer.append(event)
        else:
            self._event_bus.publish(event)

    def publish_many(self, events: tuple[OnlyEvent, ...]) -> None:
        if self._active:
            self._buffer.extend(events)
        else:
            self._event_bus.publish_many(events)

    def commit(self) -> tuple[OnlyEvent, ...]:
        if not self._active:
            raise RuntimeError("Execution event transaction is not active")
        events = tuple(self._buffer)
        self._active = False
        self._buffer = []
        self._event_bus.publish_many(events)
        return events

    def rollback(self) -> tuple[OnlyEvent, ...]:
        discarded = tuple(self._buffer)
        self._active = False
        self._buffer = []
        return discarded

    @property
    def active(self) -> bool:
        return self._active
