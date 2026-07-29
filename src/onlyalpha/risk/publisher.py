"""Risk Event publication ports and Runtime direct-event adapter."""

from typing import Protocol

from onlyalpha.event.model import OnlyEvent
from onlyalpha.event.ports import OnlyDirectEventPublicationPort


class OnlyRiskEventPublisher(Protocol):
    def publish(self, event: OnlyEvent) -> None: ...

    def publish_many(self, events: tuple[OnlyEvent, ...]) -> None: ...


class OnlyNoOpRiskEventPublisher:
    def publish(self, event: OnlyEvent) -> None:
        del event

    def publish_many(self, events: tuple[OnlyEvent, ...]) -> None:
        del events


class OnlyInMemoryRiskEventPublisher:
    def __init__(self) -> None:
        self._events: list[OnlyEvent] = []

    @property
    def events(self) -> tuple[OnlyEvent, ...]:
        return tuple(self._events)

    def publish(self, event: OnlyEvent) -> None:
        self._events.append(event)

    def publish_many(self, events: tuple[OnlyEvent, ...]) -> None:
        self._events.extend(events)


class OnlyRuntimeRiskEventPublisherAdapter:
    def __init__(self, publisher: OnlyDirectEventPublicationPort) -> None:
        self._publisher = publisher

    def publish(self, event: OnlyEvent) -> None:
        self._publisher.publish_direct(event)

    def publish_many(self, events: tuple[OnlyEvent, ...]) -> None:
        self._publisher.publish_direct_many(events)
