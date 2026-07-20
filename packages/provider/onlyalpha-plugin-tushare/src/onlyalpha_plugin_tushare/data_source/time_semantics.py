from datetime import datetime, timedelta

from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.time import OnlyTradingDay


def only_tushare_date_range(
    time_range: OnlyTimeRange, calendar: OnlyTradingCalendar
) -> tuple[str, str]:
    start_day = calendar.to_local(time_range.start).date()
    inclusive_end = calendar.to_local(time_range.end - timedelta(microseconds=1)).date()
    return start_day.strftime("%Y%m%d"), inclusive_end.strftime("%Y%m%d")


def only_daily_session(
    trading_day: OnlyTradingDay, calendar: OnlyTradingCalendar
) -> tuple[datetime, datetime]:
    intervals = calendar.session_intervals_for_trading_day(trading_day)
    if not intervals:
        raise ValueError("trade_date is not an open session in the configured calendar")
    return min(item[0] for item in intervals), max(item[1] for item in intervals)
