"""Deterministic multi-market time-model examples."""

from datetime import UTC, datetime, time

from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import OnlySessionType
from onlyalpha.domain.identifiers import OnlyCalendarId, OnlyVenueId
from onlyalpha.domain.time import OnlyTimeZone


def calendar(
    name: str,
    timezone: str,
    sessions: tuple[OnlyTradingSession, ...],
    *,
    weekend_days: tuple[int, ...] = (5, 6),
) -> OnlyTradingCalendar:
    return OnlyTradingCalendar(
        OnlyCalendarId(name),
        OnlyVenueId(name.split("-")[0]),
        OnlyTimeZone(timezone),
        sessions,
        weekend_days=weekend_days,
    )


def scenarios() -> dict[str, tuple[OnlyTradingCalendar, datetime]]:
    continuous = OnlySessionType.CONTINUOUS
    return {
        "A_SHARE": (
            calendar(
                "XSHG-EQUITY",
                "Asia/Shanghai",
                (
                    OnlyTradingSession("morning", time(9, 30), time(11, 30), continuous),
                    OnlyTradingSession("afternoon", time(13), time(15), continuous),
                ),
            ),
            datetime(2026, 7, 13, 2, 0, tzinfo=UTC),
        ),
        "HK_EQUITY": (
            calendar(
                "XHKG-EQUITY",
                "Asia/Hong_Kong",
                (
                    OnlyTradingSession("morning", time(9, 30), time(12), continuous),
                    OnlyTradingSession("afternoon", time(13), time(16), continuous),
                ),
            ),
            datetime(2026, 7, 13, 2, 0, tzinfo=UTC),
        ),
        "US_EQUITY": (
            calendar(
                "XNYS-EQUITY",
                "America/New_York",
                (
                    OnlyTradingSession("pre", time(4), time(9, 30), OnlySessionType.PRE_MARKET),
                    OnlyTradingSession("regular", time(9, 30), time(16), continuous),
                    OnlyTradingSession("post", time(16), time(20), OnlySessionType.POST_MARKET),
                ),
            ),
            datetime(2026, 7, 13, 13, 30, tzinfo=UTC),
        ),
        "CHINA_FUTURE": (
            calendar(
                "SHFE-NIGHT",
                "Asia/Shanghai",
                (
                    OnlyTradingSession("night", time(21), time(2, 30), OnlySessionType.NIGHT, 1),
                    OnlyTradingSession("day", time(9), time(15), continuous),
                ),
            ),
            datetime(2026, 7, 13, 13, 0, tzinfo=UTC),
        ),
        "CRYPTO_UTC": (
            calendar(
                "CRYPTO-UTC",
                "UTC",
                (OnlyTradingSession("24x7", time(0), time(0), continuous),),
                weekend_days=(),
            ),
            datetime(2026, 7, 13, 13, 30, tzinfo=UTC),
        ),
    }


def main() -> None:
    for name, (market_calendar, timestamp) in scenarios().items():
        session = market_calendar.session_at(timestamp)
        trading_day = market_calendar.trading_day_at(timestamp)
        print(
            name,
            timestamp.isoformat(),
            market_calendar.to_local(timestamp).isoformat(),
            trading_day.value.isoformat(),
            session.session_type if session else None,
        )


if __name__ == "__main__":
    main()
