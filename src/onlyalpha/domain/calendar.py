"""Trading calendars derive market sessions and business trading days."""

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta

from onlyalpha.domain.base import OnlyDomainModel, only_require_immutable_tuple
from onlyalpha.domain.enums import OnlySessionType
from onlyalpha.domain.errors import OnlyValidationError
from onlyalpha.domain.identifiers import OnlyCalendarId, OnlySessionProfileId, OnlyVenueId
from onlyalpha.domain.time import OnlyTimestamp, OnlyTimeZone, OnlyTradingDay, only_require_utc, only_to_utc


@dataclass(frozen=True, slots=True)
class OnlyTradingSession(OnlyDomainModel):
    name: str
    opens_at: time
    closes_at: time
    session_type: OnlySessionType = OnlySessionType.REGULAR
    belongs_to_trading_day_offset: int = 0
    allows_orders: bool = True
    allows_market_data: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise OnlyValidationError("trading session requires a name")
        if self.opens_at.tzinfo is not None or self.closes_at.tzinfo is not None:
            raise OnlyValidationError("session wall times must not contain a timezone")
        if self.belongs_to_trading_day_offset not in (-1, 0, 1):
            raise OnlyValidationError("trading-day offset must be -1, 0, or 1")

    @property
    def crosses_midnight(self) -> bool:
        return self.opens_at > self.closes_at

    @property
    def is_full_day(self) -> bool:
        return self.opens_at == self.closes_at

    def contains(self, local_time: time) -> bool:
        wall_time = local_time.replace(tzinfo=None)
        if self.is_full_day:
            return True
        if self.crosses_midnight:
            return wall_time >= self.opens_at or wall_time < self.closes_at
        return self.opens_at <= wall_time < self.closes_at

    def anchor_date(self, local_datetime: datetime) -> date:
        if self.crosses_midnight and local_datetime.time().replace(tzinfo=None) < self.closes_at:
            return local_datetime.date() - timedelta(days=1)
        return local_datetime.date()


@dataclass(frozen=True, slots=True)
class OnlySessionSchedule(OnlyDomainModel):
    trading_day: OnlyTradingDay
    sessions: tuple[OnlyTradingSession, ...]
    is_closed: bool = False

    def __post_init__(self) -> None:
        only_require_immutable_tuple(self.sessions)
        if self.is_closed and self.sessions:
            raise OnlyValidationError("closed schedule cannot contain sessions")
        if not self.is_closed and not self.sessions:
            raise OnlyValidationError("open schedule requires at least one session")


@dataclass(frozen=True, slots=True)
class OnlySessionProfile(OnlyDomainModel):
    profile_id: OnlySessionProfileId
    sessions: tuple[OnlyTradingSession, ...]

    def __post_init__(self) -> None:
        only_require_immutable_tuple(self.sessions)
        if not self.sessions:
            raise OnlyValidationError("session profile requires at least one session")


@dataclass(frozen=True, slots=True)
class OnlyTradingCalendar(OnlyDomainModel):
    calendar_id: OnlyCalendarId
    venue_id: OnlyVenueId
    timezone: OnlyTimeZone
    sessions: tuple[OnlyTradingSession, ...]
    holidays: tuple[date, ...] = ()
    weekend_days: tuple[int, ...] = (5, 6)
    session_profile_id: OnlySessionProfileId | None = None
    special_schedules: tuple[OnlySessionSchedule, ...] = ()
    calendar_version: int = 1
    effective_from: date | None = None
    effective_to: date | None = None

    def __post_init__(self) -> None:
        only_require_immutable_tuple(self.sessions, self.holidays, self.weekend_days, self.special_schedules)
        if isinstance(self.calendar_id, str):
            object.__setattr__(self, "calendar_id", OnlyCalendarId(self.calendar_id))
        if isinstance(self.timezone, str):
            object.__setattr__(self, "timezone", OnlyTimeZone(self.timezone))
        if not self.sessions:
            raise OnlyValidationError("trading calendar sessions are required")
        if self.calendar_version < 1:
            raise OnlyValidationError("calendar_version must be positive")
        if self.effective_from and self.effective_to and self.effective_from >= self.effective_to:
            raise OnlyValidationError("calendar effective interval must be increasing")
        if any(day < 0 or day > 6 for day in self.weekend_days):
            raise OnlyValidationError("weekend day must be between 0 and 6")
        if len(set(self.holidays)) != len(self.holidays):
            raise OnlyValidationError("trading calendar holidays must be unique")
        special_days = [schedule.trading_day for schedule in self.special_schedules]
        if len(special_days) != len(set(special_days)):
            raise OnlyValidationError("special session schedules must have unique trading days")

    def is_trading_day(self, day: date | OnlyTradingDay) -> bool:
        value = day.value if isinstance(day, OnlyTradingDay) else day
        special = self._special_schedule(OnlyTradingDay(value))
        if special is not None:
            return not special.is_closed
        return value.weekday() not in self.weekend_days and value not in self.holidays

    def sessions_for_trading_day(self, trading_day: OnlyTradingDay) -> tuple[OnlyTradingSession, ...]:
        special = self._special_schedule(trading_day)
        if special is not None:
            return special.sessions
        return self.sessions if self.is_trading_day(trading_day) else ()

    def session_at(self, timestamp_utc: datetime | OnlyTimestamp) -> OnlyTradingSession | None:
        local = self.to_local(timestamp_utc)
        nearby_days = []
        for offset in (-1, 0, 1):
            try:
                nearby_days.append(OnlyTradingDay(local.date() + timedelta(days=offset)))
            except OverflowError:
                # An unrepresentable neighbor is outside this lookup, not a missing session fact.
                continue
        candidates = list(self.sessions)
        for day in nearby_days:
            special = self._special_schedule(day)
            if special is not None:
                candidates.extend(special.sessions)
        for session in dict.fromkeys(candidates):
            if not session.contains(local.time()):
                continue
            trading_day = OnlyTradingDay(
                session.anchor_date(local) + timedelta(days=session.belongs_to_trading_day_offset)
            )
            configured = self.sessions_for_trading_day(trading_day)
            matched = next((item for item in configured if item == session), None)
            if matched is not None:
                return matched
        return None

    def trading_day_at(self, timestamp_utc: datetime | OnlyTimestamp) -> OnlyTradingDay:
        local = self.to_local(timestamp_utc)
        session = self.session_at(timestamp_utc)
        if session is None:
            raise OnlyValidationError("timestamp is outside a trading session")
        return OnlyTradingDay(session.anchor_date(local) + timedelta(days=session.belongs_to_trading_day_offset))

    def is_trading_time(self, timestamp_utc: datetime | OnlyTimestamp) -> bool:
        return self.session_at(timestamp_utc) is not None

    def to_local(self, timestamp_utc: datetime | OnlyTimestamp) -> datetime:
        value = timestamp_utc.to_datetime() if isinstance(timestamp_utc, OnlyTimestamp) else timestamp_utc
        only_require_utc(value, "calendar query timestamp")
        try:
            return value.astimezone(self.timezone.zone_info)
        except OverflowError as exc:
            raise OnlyValidationError("local datetime converts outside years 1..9999") from exc

    def to_utc(self, local_datetime: datetime, *, fold: int | None = None) -> datetime:
        if local_datetime.tzinfo is not None:
            return only_to_utc(local_datetime, "calendar local datetime")
        candidates: dict[int, datetime] = {}
        for candidate_fold in (0, 1):
            aware = local_datetime.replace(tzinfo=self.timezone.zone_info, fold=candidate_fold)
            utc = only_to_utc(aware, "calendar local datetime")
            roundtrip = self.to_local(utc).replace(tzinfo=None)
            if roundtrip == local_datetime:
                candidates[candidate_fold] = utc
        unique = set(candidates.values())
        if not unique:
            raise OnlyValidationError("local datetime does not exist in market timezone")
        if len(unique) > 1 and fold is None:
            raise OnlyValidationError("local datetime is ambiguous; fold is required")
        selected_fold = 0 if fold is None else fold
        if selected_fold not in candidates:
            raise OnlyValidationError("requested fold is invalid for local datetime")
        return candidates[selected_fold]

    def next_open(self, timestamp_utc: datetime) -> datetime:
        return self._boundary(timestamp_utc, forward=True, opening=True)

    def next_close(self, timestamp_utc: datetime) -> datetime:
        return self._boundary(timestamp_utc, forward=True, opening=False)

    def previous_open(self, timestamp_utc: datetime) -> datetime:
        return self._boundary(timestamp_utc, forward=False, opening=True)

    def previous_close(self, timestamp_utc: datetime) -> datetime:
        return self._boundary(timestamp_utc, forward=False, opening=False)

    def with_special_sessions(
        self, trading_day: date, sessions: tuple[OnlyTradingSession, ...]
    ) -> "OnlyTradingCalendar":
        schedule = OnlySessionSchedule(OnlyTradingDay(trading_day), sessions)
        retained = tuple(item for item in self.special_schedules if item.trading_day != schedule.trading_day)
        return replace(self, special_schedules=retained + (schedule,))

    def is_effective_on(self, day: date) -> bool:
        return (self.effective_from is None or day >= self.effective_from) and (
            self.effective_to is None or day < self.effective_to
        )

    def session_intervals_for_trading_day(self, trading_day: OnlyTradingDay) -> tuple[tuple[datetime, datetime], ...]:
        intervals: list[tuple[datetime, datetime]] = []
        for session in self.sessions_for_trading_day(trading_day):
            anchor = trading_day.value - timedelta(days=session.belongs_to_trading_day_offset)
            close_date = anchor + timedelta(days=1) if session.crosses_midnight or session.is_full_day else anchor
            intervals.append(
                (
                    self.to_utc(datetime.combine(anchor, session.opens_at)),
                    self.to_utc(datetime.combine(close_date, session.closes_at)),
                )
            )
        return tuple(intervals)

    def _special_schedule(self, trading_day: OnlyTradingDay) -> OnlySessionSchedule | None:
        return next((item for item in self.special_schedules if item.trading_day == trading_day), None)

    def _local_boundaries_for_day(self, trading_day: OnlyTradingDay, *, opening: bool) -> tuple[datetime, ...]:
        boundaries: list[datetime] = []
        for session in self.sessions_for_trading_day(trading_day):
            try:
                local_date = trading_day.value - timedelta(days=session.belongs_to_trading_day_offset)
                if not opening and (session.crosses_midnight or session.is_full_day):
                    local_date += timedelta(days=1)
            except OverflowError:
                continue
            wall_time = session.opens_at if opening else session.closes_at
            boundaries.append(datetime.combine(local_date, wall_time))
        return tuple(boundaries)

    def _boundary(self, timestamp_utc: datetime, *, forward: bool, opening: bool) -> datetime:
        only_require_utc(timestamp_utc, "calendar boundary query")
        local_day = self.to_local(timestamp_utc).date()
        best: datetime | None = None
        unresolved: list[tuple[tuple[timedelta, ...], OnlyValidationError]] = []

        def result() -> datetime:
            for differences, error in unresolved:
                if best is not None:
                    limit = best - timestamp_utc
                    if all(delta >= limit if forward else delta <= limit for delta in differences):
                        continue
                raise error
            if best is None:
                raise OnlyValidationError("no calendar boundary found within 370 days")
            return best

        direction = 1 if forward else -1
        # Session boundaries span trading_day - 1 through trading_day + 2.
        for distance in range(-2, 370):
            try:
                day = OnlyTradingDay(local_day + timedelta(days=distance * direction))
            except OverflowError:
                continue
            for local in self._local_boundaries_for_day(day, opening=opening):
                # Bound unresolved mappings; projected times never become answers.
                # This never accepts a gap or chooses a fold for a relevant boundary.
                differences = []
                for fold in (0, 1):
                    offset = local.replace(tzinfo=self.timezone.zone_info, fold=fold).utcoffset()
                    if offset is None:
                        raise OnlyValidationError("calendar timezone has no UTC offset")
                    differences.append(local - timestamp_utc.replace(tzinfo=None) - offset)
                if all(delta <= timedelta(0) if forward else delta >= timedelta(0) for delta in differences):
                    continue
                if best is not None:
                    limit = best - timestamp_utc
                    if all(delta >= limit if forward else delta <= limit for delta in differences):
                        continue
                try:
                    boundary = self.to_utc(local)
                except OnlyValidationError as error:
                    unresolved.append((tuple(differences), error))
                    continue
                if (boundary > timestamp_utc) if forward else (boundary < timestamp_utc):
                    if best is None or (boundary < best if forward else boundary > best):
                        best = boundary
            if best is not None:
                difference = (self.to_local(best).date() - day.value).days
                # Remaining owner days cannot contain a closer boundary.
                if (difference < 0) if forward else (difference >= 2):
                    return result()
        return result()


@dataclass(frozen=True, slots=True)
class OnlyTradingCalendarCatalog(OnlyDomainModel):
    calendars: tuple[OnlyTradingCalendar, ...]

    def __post_init__(self) -> None:
        only_require_immutable_tuple(self.calendars)
        keys = [(item.calendar_id, item.calendar_version) for item in self.calendars]
        if len(keys) != len(set(keys)):
            raise OnlyValidationError("calendar catalog contains a duplicate version")

    def resolve(self, calendar_id: OnlyCalendarId, day: date) -> OnlyTradingCalendar:
        matches = [item for item in self.calendars if item.calendar_id == calendar_id and item.is_effective_on(day)]
        if len(matches) != 1:
            raise OnlyValidationError(f"expected exactly one effective calendar version for {calendar_id} on {day}")
        return matches[0]
