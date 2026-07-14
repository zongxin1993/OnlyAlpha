"""Session-aware deterministic aggregation of closed time Bars."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from decimal import Decimal

from onlyalpha.core.clock import OnlyClock
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.enums import OnlyAdjustmentType, OnlyBarAggregation
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.domain.value import OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha.market_data.subscriptions import OnlyIncompleteBarPolicy, OnlyMissingBarPolicy


class OnlyBarAggregationError(Exception):
    """Input Bar cannot be deterministically assigned or aggregated."""


class OnlyBarAggregator(ABC):
    @property
    @abstractmethod
    def source_bar_type(self) -> OnlyBarType: ...

    @property
    @abstractmethod
    def target_bar_type(self) -> OnlyBarType: ...

    @abstractmethod
    def process(self, bar: OnlyBar) -> OnlyBar | None: ...


class OnlyTimeBarAggregator(OnlyBarAggregator):
    """Aggregate one-minute Bars within Calendar session boundaries."""

    def __init__(
        self,
        source_bar_type: OnlyBarType,
        target_bar_type: OnlyBarType,
        calendar: OnlyTradingCalendar,
        clock: OnlyClock,
        *,
        incomplete_policy: OnlyIncompleteBarPolicy = OnlyIncompleteBarPolicy.DROP,
        missing_policy: OnlyMissingBarPolicy = OnlyMissingBarPolicy.REJECT,
    ) -> None:
        if source_bar_type.instrument_id != target_bar_type.instrument_id:
            raise OnlyBarAggregationError("source and target instruments must match")
        if source_bar_type.specification.aggregation is not OnlyBarAggregation.TIME:
            raise OnlyBarAggregationError("source must be a time Bar")
        if target_bar_type.specification.aggregation is not OnlyBarAggregation.TIME:
            raise OnlyBarAggregationError("target must be a time Bar")
        if source_bar_type.specification.step != 1:
            raise OnlyBarAggregationError("first-phase source must be one-minute Bars")
        if target_bar_type.specification.step not in {3, 5, 15}:
            raise OnlyBarAggregationError("first-phase targets are 3m, 5m, and 15m")
        self._source_bar_type = source_bar_type
        self._target_bar_type = target_bar_type
        self._calendar = calendar
        self._clock = clock
        self._incomplete_policy = incomplete_policy
        self._missing_policy = missing_policy
        self._bars: list[OnlyBar] = []
        self._window_start: datetime | None = None
        self._window_end: datetime | None = None
        self._window_is_partial = False
        self._skipped_until: datetime | None = None

    @property
    def source_bar_type(self) -> OnlyBarType:
        return self._source_bar_type

    @property
    def target_bar_type(self) -> OnlyBarType:
        return self._target_bar_type

    def process(self, bar: OnlyBar) -> OnlyBar | None:
        if bar.bar_type != self._source_bar_type:
            raise OnlyBarAggregationError("aggregator received an unexpected BarType")
        if not bar.is_closed:
            raise OnlyBarAggregationError("aggregator accepts closed Bars only")
        if bar.revision != 0:
            raise OnlyBarAggregationError("first-phase aggregation rejects revisions")
        source_duration = timedelta(minutes=self._source_bar_type.specification.step)
        if bar.bar_end - bar.bar_start != source_duration:
            raise OnlyBarAggregationError("source Bar duration does not match BarType")
        window_start, window_end, is_partial = self._window_for(bar)
        if self._skipped_until is not None:
            if bar.bar_end < self._skipped_until:
                return None
            if bar.bar_end == self._skipped_until:
                self._skipped_until = None
                return None
        if self._window_start is not None and window_start != self._window_start:
            self._handle_incomplete_window()
        if self._window_start is None:
            if bar.bar_start != window_start:
                self._handle_missing_window(window_end)
                return None
            self._window_start = window_start
            self._window_end = window_end
            self._window_is_partial = is_partial
        if self._bars and bar.bar_start != self._bars[-1].bar_end:
            self._handle_missing_window(window_end)
            return None
        self._bars.append(bar)
        if bar.bar_end < window_end:
            return None
        if bar.bar_end > window_end:
            raise OnlyBarAggregationError("source Bar crosses a derived Bar boundary")
        if self._window_is_partial:
            return self._finish_partial_window()
        result = self._build_bar(window_start, window_end)
        self._reset()
        return result

    def _window_for(self, bar: OnlyBar) -> tuple[datetime, datetime, bool]:
        intervals = self._calendar.session_intervals_for_trading_day(OnlyTradingDay(bar.trading_day))
        session = next(
            ((start, end) for start, end in intervals if start <= bar.bar_start < end and start < bar.bar_end <= end),
            None,
        )
        if session is None:
            raise OnlyBarAggregationError("source Bar is outside its Calendar session")
        session_start, session_end = session
        duration = timedelta(minutes=self._target_bar_type.specification.step)
        elapsed = bar.bar_start - session_start
        window_index = elapsed // duration
        window_start = session_start + window_index * duration
        nominal_end = window_start + duration
        window_end = min(nominal_end, session_end)
        return window_start, window_end, nominal_end > session_end

    def _handle_incomplete_window(self) -> None:
        if not self._bars:
            self._reset()
            return
        if self._missing_policy is OnlyMissingBarPolicy.SKIP_WINDOW:
            self._reset()
            return
        raise OnlyBarAggregationError("derived Bar window ended with missing source Bars")

    def _handle_missing_window(self, window_end: datetime) -> None:
        self._reset()
        if self._missing_policy is OnlyMissingBarPolicy.SKIP_WINDOW:
            self._skipped_until = window_end
            return None
        raise OnlyBarAggregationError("source Bar sequence has a gap")

    def _finish_partial_window(self) -> OnlyBar | None:
        if self._incomplete_policy is OnlyIncompleteBarPolicy.DROP:
            self._reset()
            return None
        if self._incomplete_policy is OnlyIncompleteBarPolicy.REJECT:
            raise OnlyBarAggregationError("session ends with an incomplete derived Bar")
        raise OnlyBarAggregationError("partial Bar emission is not implemented in the first phase")

    def _build_bar(self, window_start: datetime, window_end: datetime) -> OnlyBar:
        bars = tuple(self._bars)
        self._require_consistent(bars)
        now = self._clock.now_utc()
        if now < window_end:
            raise OnlyBarAggregationError("Clock is earlier than derived Bar event time")
        quote_volume = self._sum_quantities(tuple(item.quote_volume for item in bars))
        turnover = self._sum_money(tuple(item.turnover for item in bars))
        trade_count = (
            None if any(item.trade_count is None for item in bars) else sum(item.trade_count or 0 for item in bars)
        )
        return OnlyBar(
            bar_type=self._target_bar_type,
            open=bars[0].open,
            high=OnlyPrice(max(item.high.value for item in bars), bars[0].high.precision),
            low=OnlyPrice(min(item.low.value for item in bars), bars[0].low.precision),
            close=bars[-1].close,
            volume=OnlyQuantity(sum((item.volume.value for item in bars), Decimal(0)), bars[0].volume.precision),
            quote_volume=quote_volume,
            turnover=turnover,
            trade_count=trade_count,
            open_interest=bars[-1].open_interest,
            bar_start=window_start,
            bar_end=window_end,
            ts_event=window_end,
            ts_init=now,
            is_closed=True,
            revision=0,
            adjustment_type=bars[0].adjustment_type,
            trading_day=bars[0].trading_day,
            session_type=bars[0].session_type,
        )

    @staticmethod
    def _sum_quantities(values: tuple[OnlyQuantity | None, ...]) -> OnlyQuantity | None:
        if any(value is None for value in values):
            return None
        quantities = tuple(value for value in values if value is not None)
        return OnlyQuantity(sum((value.value for value in quantities), Decimal(0)), quantities[0].precision)

    @staticmethod
    def _sum_money(values: tuple[OnlyMoney | None, ...]) -> OnlyMoney | None:
        if any(value is None for value in values):
            return None
        monies = tuple(value for value in values if value is not None)
        currency = monies[0].currency
        if any(value.currency != currency for value in monies):
            raise OnlyBarAggregationError("turnover currencies differ within a derived Bar")
        return OnlyMoney(sum((value.amount for value in monies), Decimal(0)), currency)

    @staticmethod
    def _require_consistent(bars: tuple[OnlyBar, ...]) -> None:
        if len({item.trading_day for item in bars}) != 1 or len({item.session_type for item in bars}) != 1:
            raise OnlyBarAggregationError("derived Bar cannot cross trading day or Session")
        adjustments: set[OnlyAdjustmentType] = {item.adjustment_type for item in bars}
        if len(adjustments) != 1:
            raise OnlyBarAggregationError("derived Bar adjustment types must match")

    def _reset(self) -> None:
        self._bars.clear()
        self._window_start = None
        self._window_end = None
        self._window_is_partial = False
