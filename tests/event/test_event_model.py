from datetime import UTC, datetime

from onlyalpha.event.model import OnlyEvent, OnlyEventPriority, OnlyEventSequence, OnlyEventType


def test_event_uses_strong_types_and_preserves_nanoseconds() -> None:
    event = OnlyEvent(
        "BAR_RECEIVED",
        datetime(2026, 1, 5, 1, 31, tzinfo=UTC),
        "engine",
        "runtime",
        "feed",
        7,
        timestamp_ns=1_767_576_660_000_000_123,
        ts_init_ns=1_767_576_660_000_000_123,
    )
    assert isinstance(event.event_type, OnlyEventType)
    assert isinstance(event.sequence, OnlyEventSequence)
    assert event.sequence == 7
    restored = OnlyEvent.from_dict(event.to_dict())
    assert restored == event
    assert restored.timestamp_ns == 1_767_576_660_000_000_123


def test_event_payload_bar_round_trip(closed_bar) -> None:
    event = OnlyEvent(
        "BAR_RECEIVED",
        closed_bar.ts_event,
        "engine",
        "runtime",
        "feed",
        1,
        payload=closed_bar,
        ts_init=closed_bar.ts_init,
        priority=OnlyEventPriority.HIGH,
    )
    assert OnlyEvent.from_dict(event.to_dict()) == event
