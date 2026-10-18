"""UTC absolute-time and IANA market-time value objects."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import cache
from importlib.metadata import PackageNotFoundError, version
from importlib.resources import files
from io import BytesIO
from zoneinfo import ZoneInfo

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.errors import OnlyValidationError

_UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_NANOS_PER_SECOND = 1_000_000_000
_NANOS_PER_MICROSECOND = 1_000


def _unix_integer(value: int) -> int:
    if type(value) is not int:
        raise OnlyValidationError("Unix timestamp units must be integers")
    return value


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
    try:
        return value.astimezone(UTC)
    except OverflowError as exc:
        raise OnlyValidationError(f"{field_name} converts outside years 1..9999") from exc


@dataclass(frozen=True, order=True, slots=True)
class OnlyTimestamp(OnlyDomainModel):
    """UTC instant stored as signed Unix nanoseconds."""

    unix_nanos: int

    def __post_init__(self) -> None:
        _unix_integer(self.unix_nanos)

    @classmethod
    def from_datetime(cls, value: datetime) -> "OnlyTimestamp":
        normalized = only_to_utc(value)
        delta = normalized - _UNIX_EPOCH
        nanos = (delta.days * 86_400 + delta.seconds) * _NANOS_PER_SECOND + delta.microseconds * _NANOS_PER_MICROSECOND
        return cls(nanos)

    @classmethod
    def from_unix_seconds(cls, value: int) -> "OnlyTimestamp":
        return cls(_unix_integer(value) * _NANOS_PER_SECOND)

    @classmethod
    def from_unix_millis(cls, value: int) -> "OnlyTimestamp":
        return cls(_unix_integer(value) * 1_000_000)

    @classmethod
    def from_unix_micros(cls, value: int) -> "OnlyTimestamp":
        return cls(_unix_integer(value) * _NANOS_PER_MICROSECOND)

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


@cache
def _zone_info(name: str) -> ZoneInfo:
    if "\\" in name or any(part in {"", ".", ".."} for part in name.split("/")):
        raise OnlyValidationError("timezone rules or name are not admitted")
    try:
        if version("tzdata") != "2026.3":
            raise OnlyValidationError("timezone package version is not admitted")
        resource = files("tzdata.zoneinfo")
        with resource.joinpath("tzdata.zi").open("r", encoding="utf-8") as stream:
            if stream.readline().strip() != "# version 2026c":
                raise OnlyValidationError("timezone IANA version is not admitted")
        data = resource.joinpath(*name.split("/")).read_bytes()
        return ZoneInfo.from_file(BytesIO(data), key=name)
    except (PackageNotFoundError, FileNotFoundError, IsADirectoryError, ValueError) as error:
        raise OnlyValidationError(f"unknown IANA timezone: {name}") from error


@dataclass(frozen=True, order=True, slots=True)
class OnlyTimeZone(OnlyDomainModel):
    """Validated IANA timezone name; `UTC` is the sole fixed-zone exception."""

    name: str

    def __post_init__(self) -> None:
        normalized = self.name.strip()
        if not normalized or normalized.startswith(("+", "-")) or normalized.upper().startswith("UTC+"):
            raise OnlyValidationError("timezone must use an IANA name, not a fixed UTC offset")
        _zone_info(normalized)
        object.__setattr__(self, "name", normalized)

    @property
    def zone_info(self) -> ZoneInfo:
        return _zone_info(self.name)


@dataclass(frozen=True, order=True, slots=True)
class OnlyTradingDay(OnlyDomainModel):
    """Exchange business date derived by an OnlyTradingCalendar."""

    value: date
