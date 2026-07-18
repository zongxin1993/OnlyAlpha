import os
import time
from datetime import UTC, datetime

from onlyalpha.domain.time import OnlyTimestamp


def test_timestamp_result_does_not_depend_on_process_timezone() -> None:
    original = os.environ.get("TZ")
    results: list[int] = []
    tzset = getattr(time, "tzset", None)
    try:
        for zone in ("UTC", "Asia/Shanghai", "America/New_York"):
            os.environ["TZ"] = zone
            if tzset is not None:
                tzset()
            results.append(OnlyTimestamp.from_datetime(datetime(2026, 7, 13, 13, 30, tzinfo=UTC)).to_unix_nanos())
    finally:
        if original is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original
        if tzset is not None:
            tzset()
    assert len(set(results)) == 1
