from dataclasses import replace
from datetime import date

from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingCalendarCatalog
from onlyalpha.domain.identifiers import OnlyCalendarId


def test_historical_calendar_version_is_resolved_by_business_date(
    shanghai_calendar: OnlyTradingCalendar,
) -> None:
    old = replace(
        shanghai_calendar,
        calendar_version=1,
        effective_from=date(2020, 1, 1),
        effective_to=date(2026, 1, 1),
    )
    current = replace(
        shanghai_calendar,
        calendar_version=2,
        effective_from=date(2026, 1, 1),
        effective_to=None,
    )
    catalog = OnlyTradingCalendarCatalog((old, current))
    calendar_id = OnlyCalendarId("XSHG")
    assert catalog.resolve(calendar_id, date(2025, 7, 1)).calendar_version == 1
    assert catalog.resolve(calendar_id, date(2026, 7, 1)).calendar_version == 2
