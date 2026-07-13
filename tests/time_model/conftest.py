from datetime import date, time

import pytest

from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import OnlySessionType
from onlyalpha.domain.identifiers import OnlyCalendarId, OnlyVenueId
from onlyalpha.domain.time import OnlyTimeZone


@pytest.fixture
def shanghai_calendar() -> OnlyTradingCalendar:
    return OnlyTradingCalendar(
        calendar_id=OnlyCalendarId("XSHG"),
        venue_id=OnlyVenueId("XSHG"),
        timezone=OnlyTimeZone("Asia/Shanghai"),
        sessions=(
            OnlyTradingSession("morning", time(9, 30), time(11, 30), OnlySessionType.CONTINUOUS),
            OnlyTradingSession("afternoon", time(13), time(15), OnlySessionType.CONTINUOUS),
        ),
        holidays=(date(2026, 1, 1),),
    )


@pytest.fixture
def china_future_calendar() -> OnlyTradingCalendar:
    return OnlyTradingCalendar(
        calendar_id=OnlyCalendarId("SHFE-NIGHT"),
        venue_id=OnlyVenueId("SHFE"),
        timezone=OnlyTimeZone("Asia/Shanghai"),
        sessions=(
            OnlyTradingSession(
                "night",
                time(21),
                time(2, 30),
                OnlySessionType.NIGHT,
                belongs_to_trading_day_offset=1,
            ),
            OnlyTradingSession("day", time(9), time(15), OnlySessionType.CONTINUOUS),
        ),
    )
