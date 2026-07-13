from datetime import UTC, date, datetime, time

import pytest

from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import OnlySessionType
from onlyalpha.domain.errors import OnlyValidationError
from onlyalpha.domain.identifiers import OnlyCalendarId, OnlyVenueId
from onlyalpha.domain.time import OnlyTimeZone


def _nyse() -> OnlyTradingCalendar:
    return OnlyTradingCalendar(
        OnlyCalendarId("XNYS"),
        OnlyVenueId("XNYS"),
        OnlyTimeZone("America/New_York"),
        (OnlyTradingSession("regular", time(9, 30), time(16), OnlySessionType.CONTINUOUS),),
    )


def test_market_open_tracks_dst() -> None:
    calendar = _nyse()
    assert calendar.to_utc(datetime(2026, 1, 5, 9, 30)) == datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    assert calendar.to_utc(datetime(2026, 7, 6, 9, 30)) == datetime(2026, 7, 6, 13, 30, tzinfo=UTC)


def test_nonexistent_and_ambiguous_local_times_are_explicit() -> None:
    calendar = _nyse()
    with pytest.raises(OnlyValidationError, match="does not exist"):
        calendar.to_utc(datetime(2026, 3, 8, 2, 30))
    with pytest.raises(OnlyValidationError, match="ambiguous"):
        calendar.to_utc(datetime(2026, 11, 1, 1, 30))
    first = calendar.to_utc(datetime(2026, 11, 1, 1, 30), fold=0)
    second = calendar.to_utc(datetime(2026, 11, 1, 1, 30), fold=1)
    assert first != second


def test_special_early_close_can_override_regular_session() -> None:
    calendar = _nyse().with_special_sessions(
        date(2026, 11, 27),
        (OnlyTradingSession("early", time(9, 30), time(13), OnlySessionType.CONTINUOUS),),
    )
    assert not calendar.is_trading_time(datetime(2026, 11, 27, 19, 0, tzinfo=UTC))
