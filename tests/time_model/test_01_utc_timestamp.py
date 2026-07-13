from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from onlyalpha.domain.time import OnlyTimestamp


def test_same_instant_is_equal_and_normalized_to_utc() -> None:
    utc = OnlyTimestamp.from_datetime(datetime(2026, 7, 13, 13, 30, tzinfo=UTC))
    new_york = OnlyTimestamp.from_datetime(datetime(2026, 7, 13, 9, 30, tzinfo=ZoneInfo("America/New_York")))
    tokyo = OnlyTimestamp.from_datetime(datetime(2026, 7, 13, 22, 30, tzinfo=ZoneInfo("Asia/Tokyo")))
    assert utc == new_york == tokyo
    assert utc.to_datetime().tzinfo is UTC


def test_unix_units_have_explicit_nanosecond_semantics() -> None:
    value = OnlyTimestamp.from_unix_nanos(1_752_414_600_123_456_789)
    assert value.to_unix_nanos() == 1_752_414_600_123_456_789
    assert OnlyTimestamp.from_unix_micros(value.to_unix_micros()).to_unix_nanos() == 1_752_414_600_123_456_000
