from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from onlyalpha.domain.errors import OnlyValidationError
from onlyalpha.domain.time import OnlyTimeZone


def test_timezone_requires_iana_name() -> None:
    assert OnlyTimeZone("America/New_York").zone_info.key == "America/New_York"
    with pytest.raises(OnlyValidationError, match="IANA"):
        OnlyTimeZone("+08:00")


def test_new_york_uses_different_winter_and_summer_offsets() -> None:
    zone = ZoneInfo("America/New_York")
    winter = datetime(2026, 1, 5, 9, 30, tzinfo=zone)
    summer = datetime(2026, 7, 6, 9, 30, tzinfo=zone)
    assert winter.utcoffset() != summer.utcoffset()
