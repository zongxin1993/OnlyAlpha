"""UTC absolute-time and IANA market-time value objects."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.errors import OnlyValidationError

_UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_NANOS_PER_SECOND = 1_000_000_000
_NANOS_PER_MICROSECOND = 1_000


def only_require_utc(value: datetime, field_name: str = "timestamp") -> None:
    """Reject naive and non-UTC datetime values at internal truth boundaries."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise OnlyValidationError(f"{field_name} must not be a naive datetime")
    if value.utcoffset() != timedelta(0):
        raise OnlyValidationError(f"{field_name} must be UTC")


def only_to_utc(value: datetime, field_name: str = "timestamp") -> datetime:
    """Normalize an aware datetime to the canonical stdlib UTC timezone."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise OnlyValidationError(f"{field_name} must not be a naive datetime")
    return value.astimezone(UTC)


@dataclass(frozen=True, order=True, slots=True)
class OnlyTimestamp(OnlyDomainModel):
    """UTC instant stored as signed Unix nanoseconds."""

    unix_nanos: int

    @classmethod
    def from_datetime(cls, value: datetime) -> "OnlyTimestamp":
        normalized = only_to_utc(value)
        delta = normalized - _UNIX_EPOCH
        nanos = (delta.days * 86_400 + delta.seconds) * _NANOS_PER_SECOND + delta.microseconds * _NANOS_PER_MICROSECOND
        return cls(nanos)

    @classmethod
    def from_unix_seconds(cls, value: int) -> "OnlyTimestamp":
        return cls(value * _NANOS_PER_SECOND)

    @classmethod
    def from_unix_millis(cls, value: int) -> "OnlyTimestamp":
        return cls(value * 1_000_000)

    @classmethod
    def from_unix_micros(cls, value: int) -> "OnlyTimestamp":
        return cls(value * _NANOS_PER_MICROSECOND)

    @classmethod
    def from_unix_nanos(cls, value: int) -> "OnlyTimestamp":
        return cls(value)

    def to_datetime(self) -> datetime:
        """Return UTC datetime, truncating sub-microsecond remainder."""
        seconds, nanos = divmod(self.unix_nanos, _NANOS_PER_SECOND)
        return _UNIX_EPOCH + timedelta(seconds=seconds, microseconds=nanos // 1_000)

    def to_unix_seconds(self) -> int:
        return self.unix_nanos // _NANOS_PER_SECOND

    def to_unix_millis(self) -> int:
        return self.unix_nanos // 1_000_000

    def to_unix_micros(self) -> int:
        return self.unix_nanos // _NANOS_PER_MICROSECOND

    def to_unix_nanos(self) -> int:
        return self.unix_nanos


@dataclass(frozen=True, order=True, slots=True)
class OnlyTimeZone(OnlyDomainModel):
    """Validated IANA timezone name; `UTC` is the sole fixed-zone exception."""

    name: str

    def __post_init__(self) -> None:
        normalized = self.name.strip()
        if not normalized or normalized.startswith(("+", "-")) or normalized.upper().startswith("UTC+"):
            raise OnlyValidationError("timezone must use an IANA name, not a fixed UTC offset")
        try:
            ZoneInfo(normalized)
        except ZoneInfoNotFoundError as exc:
            raise OnlyValidationError(f"unknown IANA timezone: {normalized}") from exc
        object.__setattr__(self, "name", normalized)

    @property
    def zone_info(self) -> ZoneInfo:
        return ZoneInfo(self.name)


@dataclass(frozen=True, order=True, slots=True)
class OnlyTradingDay(OnlyDomainModel):
    """Exchange business date derived by an OnlyTradingCalendar."""

    value: date
