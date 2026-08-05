from __future__ import annotations

from threading import Event
from time import monotonic

from onlyalpha.observation.publisher import OnlyCompositeObservationSink, OnlyObservationPublisher


class _RecordingSink:
    def __init__(self) -> None:
        self.items: list[object] = []

    def publish(self, snapshot: object) -> None:
        self.items.append(snapshot)


def test_composite_sinks_receive_the_exact_same_snapshot() -> None:
    left = _RecordingSink()
    right = _RecordingSink()
    snapshot = object()
    OnlyCompositeObservationSink((left, right)).publish(snapshot)  # type: ignore[arg-type]
    assert left.items == [snapshot]
    assert right.items == [snapshot]
    assert left.items[0] is right.items[0]


class _BlockingSink:
    def __init__(self) -> None:
        self.entered = Event()
        self.release = Event()
        self.items: list[object] = []

    def publish(self, snapshot: object) -> None:
        self.entered.set()
        self.release.wait(2)
        self.items.append(snapshot)


def test_slow_sink_does_not_block_producer_and_latest_is_retained() -> None:
    sink = _BlockingSink()
    publisher = OnlyObservationPublisher(sink, capacity=1)  # type: ignore[arg-type]
    publisher.start()
    first, second, latest = object(), object(), object()
    publisher.publish(first)  # type: ignore[arg-type]
    assert sink.entered.wait(1)
    started = monotonic()
    publisher.publish(second)  # type: ignore[arg-type]
    publisher.publish(latest)  # type: ignore[arg-type]
    assert monotonic() - started < 0.1
    assert publisher.drop_count == 1
    sink.release.set()
    publisher.stop()
    assert sink.items == [first, latest]


def test_stop_is_idempotent_and_rejects_late_publication() -> None:
    sink = _RecordingSink()
    publisher = OnlyObservationPublisher(sink)  # type: ignore[arg-type]
    publisher.start()
    publisher.stop()
    publisher.stop()
    publisher.publish(object())  # type: ignore[arg-type]
    assert not publisher.alive
    assert publisher.drop_count == 1
    assert sink.items == []
