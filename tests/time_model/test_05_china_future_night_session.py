from datetime import UTC, date, datetime

from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.time import OnlyTradingDay


def test_night_session_uses_session_anchor_not_utc_or_local_date(
    china_future_calendar: OnlyTradingCalendar,
) -> None:
    before_midnight = datetime(2026, 7, 13, 13, 0, tzinfo=UTC)  # Shanghai 21:00
    after_midnight = datetime(2026, 7, 13, 17, 0, tzinfo=UTC)  # Shanghai Tue 01:00
    expected = OnlyTradingDay(date(2026, 7, 14))
    assert china_future_calendar.trading_day_at(before_midnight) == expected
    assert china_future_calendar.trading_day_at(after_midnight) == expected
    assert before_midnight.date() != expected.value
