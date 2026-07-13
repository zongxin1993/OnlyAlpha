from datetime import UTC, date, datetime

from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.enums import OnlySessionType
from onlyalpha.domain.time import OnlyTradingDay


def test_a_share_midday_break_and_trading_day(
    shanghai_calendar: OnlyTradingCalendar,
) -> None:
    morning = datetime(2026, 7, 13, 2, 0, tzinfo=UTC)
    midday = datetime(2026, 7, 13, 4, 0, tzinfo=UTC)
    afternoon = datetime(2026, 7, 13, 5, 0, tzinfo=UTC)
    assert shanghai_calendar.is_trading_time(morning)
    assert not shanghai_calendar.is_trading_time(midday)
    assert shanghai_calendar.is_trading_time(afternoon)
    assert shanghai_calendar.trading_day_at(morning) == OnlyTradingDay(date(2026, 7, 13))
    assert shanghai_calendar.session_at(morning).session_type is OnlySessionType.CONTINUOUS


def test_next_open_skips_holiday(shanghai_calendar: OnlyTradingCalendar) -> None:
    query = datetime(2025, 12, 31, 8, 0, tzinfo=UTC)
    assert shanghai_calendar.next_open(query) == datetime(2026, 1, 2, 1, 30, tzinfo=UTC)
