from datetime import date, datetime, time

import pytest

from onlyalpha.domain.calendar import OnlySessionSchedule, OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import OnlyAggregationSource, OnlyBarAggregation, OnlyPriceType, OnlySessionType
from onlyalpha.domain.identifiers import (
    OnlyCalendarId,
    OnlyInstrumentId,
    OnlySymbol,
    OnlyVenueId,
)
from onlyalpha.domain.market import OnlyBarSpecification, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp, OnlyTimeZone, OnlyTradingDay
from onlyalpha.market.session_clock import OnlyMarketSessionResolver, OnlyMarketSessionState
from onlyalpha.market_data.completed_boundary import OnlyCompletedBarBoundaryResolver


def _calendar(*, holidays: tuple[date, ...] = (), special: tuple[OnlySessionSchedule, ...] = ()) -> OnlyTradingCalendar:
    return OnlyTradingCalendar(
        OnlyCalendarId("CN_XSHG"),
        OnlyVenueId("XSHG"),
        OnlyTimeZone("Asia/Shanghai"),
        (
            OnlyTradingSession("morning", time(9, 30), time(11, 30), OnlySessionType.CONTINUOUS),
            OnlyTradingSession("afternoon", time(13), time(15), OnlySessionType.CONTINUOUS),
        ),
        holidays=holidays,
        special_schedules=special,
    )


def _stamp(hour: int, minute: int = 0, second: int = 0, *, day: int = 3) -> OnlyTimestamp:
    local = datetime(2026, 8, day, hour, minute, second)
    return OnlyTimestamp.from_datetime(_calendar().to_utc(local))


@pytest.mark.parametrize(
    ("stamp", "expected"),
    [
        (_stamp(9), OnlyMarketSessionState.PRE_OPEN),
        (_stamp(10), OnlyMarketSessionState.OPEN),
        (_stamp(12, 44), OnlyMarketSessionState.BREAK),
        (_stamp(16), OnlyMarketSessionState.POST_CLOSE),
        (_stamp(10, day=8), OnlyMarketSessionState.CLOSED_DAY),
    ],
)
def test_market_session_state_is_calendar_derived(stamp: OnlyTimestamp, expected: OnlyMarketSessionState) -> None:
    snapshot = OnlyMarketSessionResolver(_calendar()).resolve(stamp)
    assert snapshot.state is expected
    assert snapshot.next_market_open.unix_nanos > stamp.unix_nanos


def test_holiday_and_special_schedule_are_authoritative() -> None:
    holiday = _calendar(holidays=(date(2026, 8, 3),))
    assert OnlyMarketSessionResolver(holiday).resolve(_stamp(10)).state is OnlyMarketSessionState.CLOSED_DAY
    special = OnlySessionSchedule(
        OnlyTradingDay(date(2026, 8, 3)),
        (OnlyTradingSession("short", time(10), time(12), OnlySessionType.CONTINUOUS),),
    )
    adjusted = _calendar(special=(special,))
    assert OnlyMarketSessionResolver(adjusted).resolve(_stamp(9)).state is OnlyMarketSessionState.PRE_OPEN
    assert OnlyMarketSessionResolver(adjusted).resolve(_stamp(10, 30)).state is OnlyMarketSessionState.OPEN
    assert OnlyMarketSessionResolver(adjusted).resolve(_stamp(13)).state is OnlyMarketSessionState.POST_CLOSE


def _bar_type(step: int) -> OnlyBarType:
    return OnlyBarType(
        OnlyInstrumentId(OnlySymbol("600000"), OnlyVenueId("XSHG")),
        OnlyBarSpecification(step, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
        OnlyAggregationSource.EXTERNAL,
    )


@pytest.mark.parametrize(
    ("stamp", "expected_local"),
    [
        (_stamp(9), datetime(2026, 7, 31, 15)),
        (_stamp(10, 21, 37), datetime(2026, 8, 3, 10, 21)),
        (_stamp(12, 44), datetime(2026, 8, 3, 11, 30)),
        (_stamp(16), datetime(2026, 8, 3, 15)),
        (_stamp(10, day=8), datetime(2026, 8, 7, 15)),
    ],
)
def test_completed_one_minute_boundary(stamp: OnlyTimestamp, expected_local: datetime) -> None:
    result = OnlyCompletedBarBoundaryResolver().latest_completed_bar_end(
        calendar=_calendar(), bar_type=_bar_type(1), observed_at=stamp
    )
    assert result.to_datetime() == _calendar().to_utc(expected_local)


def test_three_minute_boundary_restarts_at_each_session_open() -> None:
    resolver = OnlyCompletedBarBoundaryResolver()
    assert resolver.latest_completed_bar_end(
        calendar=_calendar(), bar_type=_bar_type(3), observed_at=_stamp(10, 22)
    ).to_datetime() == _calendar().to_utc(datetime(2026, 8, 3, 10, 21))
    assert resolver.latest_completed_bar_end(
        calendar=_calendar(), bar_type=_bar_type(3), observed_at=_stamp(13, 5)
    ).to_datetime() == _calendar().to_utc(datetime(2026, 8, 3, 13, 3))


def test_completed_boundary_honors_holiday_and_special_close() -> None:
    resolver = OnlyCompletedBarBoundaryResolver()
    holiday = _calendar(holidays=(date(2026, 8, 3),))
    assert resolver.latest_completed_bar_end(
        calendar=holiday, bar_type=_bar_type(1), observed_at=_stamp(10)
    ).to_datetime() == holiday.to_utc(datetime(2026, 7, 31, 15))
    special = OnlySessionSchedule(
        OnlyTradingDay(date(2026, 8, 3)),
        (OnlyTradingSession("short", time(10), time(12), OnlySessionType.CONTINUOUS),),
    )
    adjusted = _calendar(special=(special,))
    assert resolver.latest_completed_bar_end(
        calendar=adjusted, bar_type=_bar_type(1), observed_at=_stamp(13)
    ).to_datetime() == adjusted.to_utc(datetime(2026, 8, 3, 12))


def test_completed_boundary_supports_cross_midnight_session() -> None:
    night = OnlyTradingCalendar(
        OnlyCalendarId("NIGHT"),
        OnlyVenueId("NIGHT"),
        OnlyTimeZone("Asia/Shanghai"),
        (OnlyTradingSession("night", time(21), time(2), OnlySessionType.CONTINUOUS),),
        weekend_days=(),
    )
    observed = OnlyTimestamp.from_datetime(night.to_utc(datetime(2026, 8, 4, 1, 14, 37)))
    assert OnlyCompletedBarBoundaryResolver().latest_completed_bar_end(
        calendar=night, bar_type=_bar_type(1), observed_at=observed
    ).to_datetime() == night.to_utc(datetime(2026, 8, 4, 1, 14))
