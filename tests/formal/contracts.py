from __future__ import annotations

from onlyalpha.domain.time import OnlyTimestamp


def unix_micros_round_trip(value: int) -> int:
    """
    Convert through the timestamp value object without losing microseconds.

    post: _ == value
    """
    return OnlyTimestamp.from_unix_micros(value).to_unix_micros()


def unix_millis_round_trip(value: int) -> int:
    """
    Convert through nanoseconds without losing millisecond precision.

    post: _ == value
    """
    return OnlyTimestamp.from_unix_millis(value).to_unix_millis()


def timestamp_unit_hierarchy(value: int) -> bool:
    """
    The public constructors must agree on exact unit conversion.

    post: _
    """
    return OnlyTimestamp.from_unix_seconds(value) == OnlyTimestamp.from_unix_millis(value * 1_000)
