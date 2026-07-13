from datetime import UTC, date, datetime

from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.identifiers import OnlyCalendarId
from onlyalpha.domain.time import OnlyTimestamp, OnlyTimeZone, OnlyTradingDay
from onlyalpha.event.model import OnlyEvent


def test_timestamp_timezone_and_trading_day_json_roundtrip() -> None:
    timestamp = OnlyTimestamp.from_datetime(datetime(2026, 7, 13, 13, 0, 0, 123456, tzinfo=UTC))
    assert OnlyTimestamp.from_json(timestamp.to_json()) == timestamp
    assert OnlyTimeZone.from_json(OnlyTimeZone("Asia/Shanghai").to_json()) == OnlyTimeZone("Asia/Shanghai")
    assert OnlyTradingDay.from_json(OnlyTradingDay(date(2026, 7, 14)).to_json()) == OnlyTradingDay(date(2026, 7, 14))
    assert OnlyCalendarId.from_json(OnlyCalendarId("SHFE").to_json()) == OnlyCalendarId("SHFE")
    assert timestamp.to_datetime().isoformat().endswith("+00:00")


def test_event_roundtrip_uses_explicit_utc_fields() -> None:
    event = OnlyEvent(
        "tick",
        datetime(2026, 7, 13, 13, 0, tzinfo=UTC),
        "engine",
        "runtime",
        "feed",
        1,
    )
    payload = event.to_dict()
    assert payload["ts_event"] == "2026-07-13T13:00:00Z"
    assert OnlyEvent.from_dict(payload) == event


def test_calendar_roundtrip_keeps_iana_timezone_and_ids(
    shanghai_calendar: OnlyTradingCalendar,
) -> None:
    restored = OnlyTradingCalendar.from_json(shanghai_calendar.to_json())
    assert restored == shanghai_calendar
    assert restored.timezone.name == "Asia/Shanghai"
