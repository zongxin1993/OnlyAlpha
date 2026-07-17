from datetime import UTC, datetime

from onlyalpha.domain.enums import OnlyTimeDisplayMode
from onlyalpha.domain.time import OnlyTimestamp, OnlyTimeZone
from onlyalpha.utils.time_conversion import OnlyTimeConversionService


def test_display_conversion_never_changes_utc_truth() -> None:
    timestamp = OnlyTimestamp.from_datetime(datetime(2026, 7, 13, 13, 30, tzinfo=UTC))
    service = OnlyTimeConversionService()
    utc = service.convert(timestamp, OnlyTimeDisplayMode.UTC)
    market = service.convert(
        timestamp,
        OnlyTimeDisplayMode.MARKET,
        market_timezone=OnlyTimeZone("America/New_York"),
    )
    user = service.convert(
        timestamp,
        OnlyTimeDisplayMode.USER_LOCAL,
        user_timezone=OnlyTimeZone("Asia/Tokyo"),
    )
    assert utc.timestamp_utc == market.timestamp_utc == user.timestamp_utc
    assert market.display_time.isoformat() == "2026-07-13T09:30:00-04:00"
    assert user.display_time.isoformat() == "2026-07-13T22:30:00+09:00"
