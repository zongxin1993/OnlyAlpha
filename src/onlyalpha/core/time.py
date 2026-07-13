"""Exact conversion helpers for UTC instants and Unix nanoseconds."""

from datetime import UTC, datetime, timedelta

from onlyalpha.core.errors import OnlyValidationError

ONLY_NANOSECONDS_PER_SECOND = 1_000_000_000
ONLY_NANOSECONDS_PER_MICROSECOND = 1_000
_ONLY_UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def only_ensure_utc_aware(value: datetime, *, field_name: str = "timestamp") -> datetime:
    """Normalize an aware datetime to UTC and reject naive input."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise OnlyValidationError(f"{field_name} must not be naive")
    return value.astimezone(UTC)


def only_datetime_to_unix_ns(value: datetime) -> int:
    """Convert an aware datetime without using floating-point seconds."""
    normalized = only_ensure_utc_aware(value)
    delta = normalized - _ONLY_UNIX_EPOCH
    return (
        delta.days * 86_400 + delta.seconds
    ) * ONLY_NANOSECONDS_PER_SECOND + delta.microseconds * ONLY_NANOSECONDS_PER_MICROSECOND


def only_unix_ns_to_datetime_utc(value: int, *, allow_truncation: bool = False) -> datetime:
    """Convert Unix nanoseconds to UTC datetime.

    Python ``datetime`` cannot represent sub-microsecond precision. The public
    converter rejects that loss by default; Clock compatibility views opt in to
    truncation while retaining the authoritative nanosecond integer.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise OnlyValidationError("Unix nanoseconds must be an integer")
    seconds, nanos = divmod(value, ONLY_NANOSECONDS_PER_SECOND)
    if nanos % ONLY_NANOSECONDS_PER_MICROSECOND and not allow_truncation:
        raise OnlyValidationError("datetime cannot represent sub-microsecond nanoseconds")
    try:
        return _ONLY_UNIX_EPOCH + timedelta(seconds=seconds, microseconds=nanos // 1_000)
    except OverflowError as exc:
        raise OnlyValidationError("Unix nanoseconds are outside datetime range") from exc
