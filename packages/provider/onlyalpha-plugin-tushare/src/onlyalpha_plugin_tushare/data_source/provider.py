from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import Decimal

from onlyalpha.cache.historical.models import (
    OnlyDataQualityReport,
    OnlyHistoricalCacheKey,
    OnlyHistoricalDataRequest,
    OnlyHistoricalFetchResult,
)
from onlyalpha.core.ranges import OnlyTimeRange, only_merge_ranges
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlyBarAggregation,
    OnlySessionType,
)
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.market import OnlyBar
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.domain.value import OnlyMoney, OnlyPrice, OnlyQuantity

from ..errors import OnlyTushareError
from ..sdk.adapter import OnlyTushareClient
from .mapping import only_to_tushare_asset, only_to_tushare_symbol
from .time_semantics import only_daily_session, only_tushare_date_range
from .validation import only_exact_decimal, only_validate_response


class OnlyTushareHistoricalDataProvider:
    def __init__(
        self,
        source_id: str,
        instrument: OnlyInstrument,
        calendar: OnlyTradingCalendar,
        client_factory: Callable[[], OnlyTushareClient],
    ) -> None:
        self._source_id = source_id
        self._instrument = instrument
        self._calendar = calendar
        self._client_factory = client_factory

    def build_cache_key(
        self, request: OnlyHistoricalDataRequest
    ) -> OnlyHistoricalCacheKey:
        return OnlyHistoricalCacheKey(
            self._source_id,
            "bars",
            request.instrument_id,
            request.bar_type,
            request.price_adjustment,
            request.adjustment_reference,
            time_semantics_version=2,
        )

    def fetch(
        self, request: OnlyHistoricalDataRequest, time_range: OnlyTimeRange
    ) -> OnlyHistoricalFetchResult:
        if (
            request.bar_type.specification.aggregation is not OnlyBarAggregation.TIME
            or request.bar_type.specification.step != 1440
        ):
            raise OnlyTushareError(
                "TUSHARE_UNSUPPORTED_BAR_TYPE",
                "only 1440-minute daily Bars are supported",
            )
        symbol = only_to_tushare_symbol(request.instrument_id)
        asset = only_to_tushare_asset(self._instrument)
        start_date, end_date = only_tushare_date_range(time_range, self._calendar)
        adjustment = {
            OnlyAdjustmentType.RAW: None,
            OnlyAdjustmentType.FORWARD: "qfq",
            OnlyAdjustmentType.BACKWARD: "hfq",
        }[request.price_adjustment]
        try:
            raw = self._client_factory().pro_bar(
                ts_code=symbol,
                start_date=start_date,
                end_date=end_date,
                asset=asset,
                freq="D",
                adj=adjustment,
            )
        except OnlyTushareError:
            raise
        except Exception as exc:
            raise OnlyTushareError(
                "TUSHARE_REQUEST_FAILED", "Tushare daily Bar request failed"
            ) from exc
        rows, issues = only_validate_response(raw, symbol)
        if not rows and self._contains_trading_day(time_range):
            raise OnlyTushareError(
                "TUSHARE_EMPTY_RESPONSE",
                "empty response cannot be confirmed as a legal result",
            )
        bars = tuple(self._bar(request, row) for row in rows)
        observed = only_merge_ranges(
            tuple(OnlyTimeRange(item.bar_start, item.bar_end) for item in bars)
        )
        return OnlyHistoricalFetchResult(
            bars,
            (time_range,),
            observed,
            OnlyDataQualityReport(True, issues),
            {
                "vendor": "tushare",
                "request_api": "pro_bar",
                "frequency": "D",
                "asset": asset,
                "price_adjustment": request.price_adjustment.value,
                "source_timezone": "Asia/Shanghai",
            },
        )

    def _bar(
        self, request: OnlyHistoricalDataRequest, values: Mapping[str, object]
    ) -> OnlyBar:
        day = OnlyTradingDay(
            datetime.strptime(str(values["trade_date"]), "%Y%m%d").date()
        )
        start, end = only_daily_session(day, self._calendar)

        def price(name: str) -> OnlyPrice:
            return OnlyPrice(
                only_exact_decimal(values[name]), self._instrument.price_precision
            )

        volume = (only_exact_decimal(values["vol"]) * Decimal("100")).normalize()
        amount_value = values.get("amount")
        turnover = (
            None
            if amount_value is None
            else OnlyMoney(
                (only_exact_decimal(amount_value) * Decimal("1000")).normalize(),
                self._instrument.quote_currency,
            )
        )
        return OnlyBar(
            bar_type=request.bar_type,
            open=price("open"),
            high=price("high"),
            low=price("low"),
            close=price("close"),
            volume=OnlyQuantity(volume, self._instrument.quantity_precision),
            quote_volume=None,
            turnover=turnover,
            trade_count=None,
            open_interest=None,
            bar_start=start,
            bar_end=end,
            ts_event=end,
            ts_init=end,
            is_closed=True,
            revision=0,
            adjustment_type=request.price_adjustment,
            trading_day=day.value,
            session_type=OnlySessionType.REGULAR,
        )

    def _contains_trading_day(self, time_range: OnlyTimeRange) -> bool:
        start = self._calendar.to_local(time_range.start).date()
        end = self._calendar.to_local(time_range.end).date()
        day = start
        while day <= end:
            if self._calendar.is_trading_day(day):
                return True
            day = day.fromordinal(day.toordinal() + 1)
        return False
