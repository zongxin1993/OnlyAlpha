from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.core.errors import OnlyValidationError as OnlyCoreValidationError
from onlyalpha.domain.errors import OnlyValidationError as OnlyDomainValidationError
from onlyalpha.domain.time import OnlyTimeZone
from onlyalpha.event.model import OnlyEvent
from onlyalpha.utils.time_conversion import migrate_legacy_datetime


def test_event_and_backtest_clock_reject_non_utc_internal_time() -> None:
    local = datetime(2026, 7, 13, 9, 30, tzinfo=ZoneInfo("America/New_York"))
    with pytest.raises(OnlyCoreValidationError, match="UTC"):
        OnlyBacktestClock(local)
    with pytest.raises(ValueError, match="UTC"):
        OnlyEvent("tick", local, "e", "r", "feed", 1)


def test_legacy_naive_migration_requires_source_timezone() -> None:
    value = datetime(2026, 7, 13, 9, 30)
    with pytest.raises(OnlyDomainValidationError, match="source timezone"):
        migrate_legacy_datetime(value)
    migrated = migrate_legacy_datetime(value, source_timezone=OnlyTimeZone("Asia/Shanghai"))
    assert migrated == datetime(2026, 7, 13, 1, 30, tzinfo=UTC)
