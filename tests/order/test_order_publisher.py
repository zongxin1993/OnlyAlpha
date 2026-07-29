from datetime import UTC, datetime

from onlyalpha.domain.identifiers import OnlyEngineId, OnlyRuntimeId
from onlyalpha.event.model import OnlyEvent
from onlyalpha.event.ports import OnlyRuntimeEventDisposition, OnlyRuntimeEventPublicationResult, OnlyRuntimeEventRoute
from onlyalpha.order.publisher import OnlyRuntimeOrderEventPublisherAdapter


class OnlyRecordingDirectPublisher:
    def __init__(self) -> None:
        self.events: list[OnlyEvent] = []

    def publish_direct(self, event: OnlyEvent) -> OnlyRuntimeEventPublicationResult:
        return self.publish_direct_many((event,))

    def publish_direct_many(self, events: tuple[OnlyEvent, ...]) -> OnlyRuntimeEventPublicationResult:
        self.events.extend(events)
        count = len(events)
        return OnlyRuntimeEventPublicationResult(
            OnlyRuntimeEventRoute.EXTERNAL_DIRECT,
            OnlyRuntimeEventDisposition.PUBLISHED,
            count,
            count,
            0,
            0,
            0,
        )


def test_runtime_order_publisher_uses_direct_publication_port() -> None:
    port = OnlyRecordingDirectPublisher()
    adapter = OnlyRuntimeOrderEventPublisherAdapter(port)
    events = tuple(
        OnlyEvent(
            "ORDER_TEST",
            datetime(2026, 1, 1, tzinfo=UTC),
            OnlyEngineId("engine"),
            OnlyRuntimeId("runtime"),
            "test",
            sequence,
        )
        for sequence in (1, 2)
    )
    adapter.publish(events[0])
    adapter.publish_many(events[1:])
    assert port.events == list(events)
