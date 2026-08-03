"""Calendar-aware authority for the latest completed time-Bar boundary."""

from datetime import timedelta

from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.enums import OnlyBarAggregation
from onlyalpha.domain.market import OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.market.session_clock import OnlyMarketSessionResolver, OnlyMarketSessionState


class OnlyCompletedBarBoundaryResolver:
    def latest_completed_bar_end(
        self,
        *,
        calendar: OnlyTradingCalendar,
        bar_type: OnlyBarType,
        observed_at: OnlyTimestamp,
    ) -> OnlyTimestamp:
        if bar_type.specification.aggregation is not OnlyBarAggregation.TIME:
            raise ValueError("completed boundary currently supports TIME Bars only")
        snapshot = OnlyMarketSessionResolver(calendar).resolve(observed_at)
        observed = observed_at.to_datetime()
        if snapshot.state is OnlyMarketSessionState.OPEN:
            assert snapshot.current_trading_day is not None
            intervals = calendar.session_intervals_for_trading_day(snapshot.current_trading_day)
            active = next((item for item in intervals if item[0] <= observed < item[1]), None)
            if active is None:
                raise RuntimeError("Calendar active Session has no matching interval")
            duration = timedelta(minutes=bar_type.specification.step)
            completed = int((observed - active[0]) // duration)
            if completed > 0:
                return OnlyTimestamp.from_datetime(active[0] + completed * duration)
        if snapshot.previous_market_close is None:
            raise ValueError("no completed market Session found within Calendar search horizon")
        return snapshot.previous_market_close
