from datetime import UTC, date, datetime

from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.time import OnlyTradingDay


def test_daily_session_intervals_follow_market_sessions(
    shanghai_calendar: OnlyTradingCalendar,
) -> None:
    intervals = shanghai_calendar.session_intervals_for_trading_day(OnlyTradingDay(date(2026, 7, 13)))
    assert intervals == (
        (
            datetime(2026, 7, 13, 1, 30, tzinfo=UTC),
            datetime(2026, 7, 13, 3, 30, tzinfo=UTC),
        ),
        (
            datetime(2026, 7, 13, 5, 0, tzinfo=UTC),
            datetime(2026, 7, 13, 7, 0, tzinfo=UTC),
        ),
    )
    assert intervals[0][1] != intervals[1][0]
