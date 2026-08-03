"""Calendar-derived market-session state for long-lived runtimes."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum

from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.identifiers import OnlyCalendarId
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay


class OnlyMarketSessionState(StrEnum):
    PRE_OPEN = "PRE_OPEN"
    OPEN = "OPEN"
    BREAK = "BREAK"
    POST_CLOSE = "POST_CLOSE"
    CLOSED_DAY = "CLOSED_DAY"


@dataclass(frozen=True, slots=True)
class OnlyMarketSessionSnapshot:
    observed_at: OnlyTimestamp
    calendar_id: OnlyCalendarId
    state: OnlyMarketSessionState
    local_date: date
    local_time: time
    active_session: OnlyTradingSession | None
    current_trading_day: OnlyTradingDay | None
    previous_trading_day: OnlyTradingDay | None
    next_trading_day: OnlyTradingDay
    previous_market_close: OnlyTimestamp | None
    next_market_open: OnlyTimestamp
    next_market_close: OnlyTimestamp


class OnlyMarketSessionResolver:
    """Resolve lifecycle-independent market state from the Calendar authority."""

    def __init__(self, calendar: OnlyTradingCalendar) -> None:
        self._calendar = calendar

    def resolve(self, timestamp: OnlyTimestamp) -> OnlyMarketSessionSnapshot:
        observed = timestamp.to_datetime()
        local = self._calendar.to_local(observed)
        active = self._calendar.session_at(timestamp)
        local_day = OnlyTradingDay(local.date())
        current = self._calendar.trading_day_at(timestamp) if active is not None else None
        intervals = self._calendar.session_intervals_for_trading_day(local_day)
        if active is not None:
            state = OnlyMarketSessionState.OPEN
        elif not self._calendar.is_trading_day(local_day):
            state = OnlyMarketSessionState.CLOSED_DAY
        elif intervals and observed < intervals[0][0]:
            state = OnlyMarketSessionState.PRE_OPEN
            current = local_day
        elif intervals and observed >= intervals[-1][1]:
            state = OnlyMarketSessionState.POST_CLOSE
            current = local_day
        else:
            state = OnlyMarketSessionState.BREAK
            current = local_day

        next_open = self._calendar.next_open(observed)
        next_close = self._calendar.next_close(observed)
        next_day = self._calendar.trading_day_at(next_open)
        previous_close = self._latest_close_not_after(observed)
        latest_closed_day = (
            None
            if previous_close is None
            else self._calendar.trading_day_at(previous_close - timedelta(microseconds=1))
        )
        previous_day = self._previous_trading_day(current) if current is not None else latest_closed_day
        return OnlyMarketSessionSnapshot(
            timestamp,
            self._calendar.calendar_id,
            state,
            local.date(),
            local.time().replace(tzinfo=None),
            active,
            current,
            previous_day,
            next_day,
            None if previous_close is None else OnlyTimestamp.from_datetime(previous_close),
            OnlyTimestamp.from_datetime(next_open),
            OnlyTimestamp.from_datetime(next_close),
        )

    def _latest_close_not_after(self, observed: datetime) -> datetime | None:
        local_date = self._calendar.to_local(observed).date()
        for distance in range(0, 370):
            day = OnlyTradingDay(local_date - timedelta(days=distance))
            candidates = tuple(
                end for _, end in self._calendar.session_intervals_for_trading_day(day) if end <= observed
            )
            if candidates:
                return max(candidates)
        return None

    def _previous_trading_day(self, current: OnlyTradingDay) -> OnlyTradingDay | None:
        for distance in range(1, 370):
            candidate = OnlyTradingDay(current.value - timedelta(days=distance))
            if self._calendar.is_trading_day(candidate):
                return candidate
        return None
