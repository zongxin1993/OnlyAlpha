"""Trading calendar and session value objects."""

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.errors import OnlyValidationError
from onlyalpha.domain.identifiers import OnlyVenueId


@dataclass(frozen=True, slots=True)
class OnlyTradingSession(OnlyDomainModel):
    name: str
    opens_at: time
    closes_at: time

    def __post_init__(self) -> None:
        if not self.name.strip() or self.opens_at == self.closes_at:
            raise OnlyValidationError("trading session requires a name and distinct local times")

    @property
    def crosses_midnight(self) -> bool:
        return self.opens_at > self.closes_at

    def contains(self, local_time: time) -> bool:
        if self.crosses_midnight:
            return local_time >= self.opens_at or local_time < self.closes_at
        return self.opens_at <= local_time < self.closes_at


@dataclass(frozen=True, slots=True)
class OnlyTradingCalendar(OnlyDomainModel):
    calendar_id: str
    venue_id: OnlyVenueId
    timezone: str
    sessions: tuple[OnlyTradingSession, ...]
    holidays: tuple[date, ...] = ()
    weekend_days: tuple[int, ...] = (5, 6)

    def __post_init__(self) -> None:
        if not self.calendar_id.strip() or not self.sessions:
            raise OnlyValidationError("trading calendar id and sessions are required")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise OnlyValidationError(f"unknown timezone: {self.timezone}") from exc
        if any(day < 0 or day > 6 for day in self.weekend_days):
            raise OnlyValidationError("weekend day must be between 0 and 6")
        if len(set(self.holidays)) != len(self.holidays):
            raise OnlyValidationError("trading calendar holidays must be unique")

    def is_trading_day(self, day: date) -> bool:
        return day.weekday() not in self.weekend_days and day not in self.holidays

    def is_open_at(self, timestamp: datetime) -> bool:
        if timestamp.tzinfo is None:
            raise OnlyValidationError("calendar query timestamp must be timezone-aware")
        local = timestamp.astimezone(ZoneInfo(self.timezone))
        if not self.is_trading_day(local.date()):
            return False
        return any(session.contains(local.time().replace(tzinfo=None)) for session in self.sessions)
