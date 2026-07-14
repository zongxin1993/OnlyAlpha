"""Order event publication ports and Runtime EventBus adapter."""

from typing import Protocol

from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.event.model import OnlyEvent


class OnlyOrderEventPublisher(Protocol):
    def publish(self, event: OnlyEvent) -> None: ...

    def publish_many(self, events: tuple[OnlyEvent, ...]) -> None: ...


class OnlyNoOpOrderEventPublisher:
    def publish(self, event: OnlyEvent) -> None:
        del event

    def publish_many(self, events: tuple[OnlyEvent, ...]) -> None:
        del events


class OnlyInMemoryOrderEventPublisher:
    def __init__(self) -> None:
        self._events: list[OnlyEvent] = []

    @property
    def events(self) -> tuple[OnlyEvent, ...]:
        return tuple(self._events)

    def publish(self, event: OnlyEvent) -> None:
        self._events.append(event)

    def publish_many(self, events: tuple[OnlyEvent, ...]) -> None:
        self._events.extend(events)


class OnlyRuntimeOrderEventPublisherAdapter:
    def __init__(self, event_bus: OnlyEventBus) -> None:
        self._event_bus = event_bus

    def publish(self, event: OnlyEvent) -> None:
        self._event_bus.publish(event)

    def publish_many(self, events: tuple[OnlyEvent, ...]) -> None:
        self._event_bus.publish_many(events)
