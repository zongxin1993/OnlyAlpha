"""Both language implementations must consume the same exact upstream rules."""

from datetime import datetime

import pytest

from onlyalpha.domain.errors import OnlyValidationError
from onlyalpha.domain.time import OnlyTimeZone


def test_timezone_does_not_depend_on_system_zoneinfo(monkeypatch) -> None:
    import onlyalpha.domain.time as module

    original = module.ZoneInfo

    class PinnedOnly:
        def __new__(cls, *args, **kwargs):
            raise AssertionError("ambient timezone discovery")

        from_file = staticmethod(original.from_file)

    # The OS lookup constructor must never select canonical rules.
    module._zone_info.cache_clear()
    monkeypatch.setattr(module, "ZoneInfo", PinnedOnly)
    assert OnlyTimeZone("America/New_York").zone_info.utcoffset(datetime(2025, 7, 1)).total_seconds() == -14400


@pytest.mark.parametrize("name", ["../UTC", "/UTC", "Etc/../UTC", "UTC+08:00"])
def test_timezone_names_cannot_escape_the_pinned_dataset(name) -> None:
    with pytest.raises(OnlyValidationError):
        OnlyTimeZone(name)


@pytest.mark.parametrize(
    "offset,query,expected,method",
    [
        (1, "2025-01-06T08:00:00+00:00", "2025-01-06T09:00:00+00:00", "next_open"),
        (-1, "2025-01-06T10:00:00+00:00", "2025-01-06T09:00:00+00:00", "previous_open"),
    ],
)
def test_calendar_boundaries_compare_neighboring_trading_day_offsets(offset, query, expected, method) -> None:
    from datetime import time

    from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
    from onlyalpha.domain.identifiers import OnlyCalendarId, OnlyVenueId

    calendar = OnlyTradingCalendar(
        OnlyCalendarId("TEST"),
        OnlyVenueId("TEST"),
        OnlyTimeZone("UTC"),
        (
            OnlyTradingSession("ordinary", time(12 if offset == 1 else 7), time(13 if offset == 1 else 8)),
            OnlyTradingSession("shifted", time(9), time(10), belongs_to_trading_day_offset=offset),
        ),
        weekend_days=(),
    )
    assert getattr(calendar, method)(datetime.fromisoformat(query)) == datetime.fromisoformat(expected)


@pytest.mark.parametrize("year,month,day", [(1, 1, 1), (9999, 12, 31)])
def test_session_queries_ignore_unrepresentable_neighbor_dates(year, month, day) -> None:
    from datetime import UTC, time

    from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
    from onlyalpha.domain.identifiers import OnlyCalendarId, OnlyVenueId

    session = OnlyTradingSession("day", time(9), time(17))
    calendar = OnlyTradingCalendar(
        OnlyCalendarId("TEST"),
        OnlyVenueId("TEST"),
        OnlyTimeZone("UTC"),
        (session,),
        weekend_days=(),
    )
    assert calendar.session_at(datetime(year, month, day, 10, tzinfo=UTC)) == session
