from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from onlyalpha.core.errors import OnlyValidationError
from onlyalpha.core.time import only_datetime_to_unix_ns, only_ensure_utc_aware, only_unix_ns_to_datetime_utc


def test_conversion_normalizes_aware_values_without_float() -> None:
    local = datetime(2026, 1, 5, 9, 30, 0, 123456, tzinfo=ZoneInfo("Asia/Shanghai"))
    utc = datetime(2026, 1, 5, 1, 30, 0, 123456, tzinfo=UTC)
    assert only_ensure_utc_aware(local) == utc
    assert only_unix_ns_to_datetime_utc(only_datetime_to_unix_ns(local)) == utc


def test_conversion_rejects_naive_and_submicrosecond_loss() -> None:
    with pytest.raises(OnlyValidationError, match="naive"):
        only_datetime_to_unix_ns(datetime(2026, 1, 1))
    with pytest.raises(OnlyValidationError, match="sub-microsecond"):
        only_unix_ns_to_datetime_utc(1)
    assert only_unix_ns_to_datetime_utc(1, allow_truncation=True) == datetime(1970, 1, 1, tzinfo=UTC)


def test_negative_timestamp_round_trip() -> None:
    value = datetime(1969, 12, 31, 23, 59, 59, 999999, tzinfo=UTC)
    assert only_datetime_to_unix_ns(value) == -1_000
    assert only_unix_ns_to_datetime_utc(-1_000) == value
