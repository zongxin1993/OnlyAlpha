"""Immutable streaming-recovery evidence and calendar-pure boundary helpers."""

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from onlyalpha.data.models import OnlyMarketDataInboundUpdate
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay


class OnlyStreamingRecoveryReason(StrEnum):
    GAP = "GAP"
    STALE = "STALE"
    DISCONNECTED = "DISCONNECTED"


@dataclass(frozen=True, slots=True)
class OnlyStreamingRecoveryPlan:
    generation: int
    reason: OnlyStreamingRecoveryReason
    instrument_id: OnlyInstrumentId
    bar_type: OnlyBarType
    confirmed_bar_end: OnlyTimestamp
    recovery_target: OnlyTimestamp
    trigger_update: OnlyMarketDataInboundUpdate | None = None


def only_expected_closed_bar_boundaries(
    *,
    calendar: OnlyTradingCalendar,
    bar_type: OnlyBarType,
    confirmed_bar_end: OnlyTimestamp,
    recovery_target: OnlyTimestamp,
) -> tuple[OnlyTimestamp, ...]:
    """Return required closed Bar ends after the frontier through the target."""
    if recovery_target.unix_nanos <= confirmed_bar_end.unix_nanos:
        return ()
    duration = timedelta(minutes=bar_type.specification.step)
    start = confirmed_bar_end.to_datetime()
    target = recovery_target.to_datetime()
    local_start = calendar.to_local(start).date() - timedelta(days=1)
    local_target = calendar.to_local(target).date() + timedelta(days=1)
    boundaries: list[OnlyTimestamp] = []
    day = local_start
    while day <= local_target:
        for session_start, session_end in calendar.session_intervals_for_trading_day(OnlyTradingDay(day)):
            boundary = session_start + duration
            while boundary <= session_end:
                if start < boundary <= target:
                    boundaries.append(OnlyTimestamp.from_datetime(boundary))
                boundary += duration
        day += timedelta(days=1)
    return tuple(sorted(set(boundaries), key=lambda item: item.unix_nanos))
