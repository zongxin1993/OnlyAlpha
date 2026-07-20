from datetime import date, time
from decimal import Decimal

from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import OnlyMarketType
from onlyalpha.domain.identifiers import OnlyCalendarId, OnlyRawSymbol, OnlyVenueId
from onlyalpha.domain.instrument import OnlyEquity, OnlyETF, OnlyIndex
from onlyalpha.domain.time import OnlyTimeZone
from onlyalpha.domain.value import OnlyCurrency, OnlyMultiplier, OnlyPrice, OnlyQuantity

from ..mapping.exchange import to_xt_symbol


def instrument(xtdata, instrument_id):
    detail = xtdata.get_instrument_detail(to_xt_symbol(instrument_id))
    if not detail:
        return None
    code = str(instrument_id.symbol)
    cls = (
        OnlyETF
        if code.startswith(("51", "15"))
        else OnlyIndex
        if code.startswith(("000", "399")) and len(code) == 6
        else OnlyEquity
    )
    return cls(
        instrument_id=instrument_id,
        raw_symbol=OnlyRawSymbol(code),
        market_type=OnlyMarketType.CASH,
        quote_currency=OnlyCurrency("CNY", 2),
        settlement_currency=OnlyCurrency("CNY", 2),
        price_precision=4,
        quantity_precision=0,
        tick_size=OnlyPrice(Decimal(str(detail.get("PriceTick", "0.01"))), 4),
        step_size=OnlyQuantity(Decimal("1"), 0),
        contract_multiplier=OnlyMultiplier(Decimal(str(detail.get("VolumeMultiple", 1))), 0),
        lot_size=OnlyQuantity(Decimal(str(detail.get("MinLimitOrderVolume", 100))), 0),
        timezone="Asia/Shanghai",
    )


def calendar(xtdata, calendar_id):
    venue = "XSHG" if "SH" in str(calendar_id).upper() else "XSHE"
    market = "SH" if venue == "XSHG" else "SZ"
    days = xtdata.get_trading_calendar(market) or []
    parsed = {
        date.fromisoformat(
            str(day).replace("-", "")[:4] + "-" + str(day).replace("-", "")[4:6] + "-" + str(day).replace("-", "")[6:8]
        )
        for day in days
    }
    span = range((max(parsed) - min(parsed)).days + 1) if parsed else ()
    holidays = tuple(
        min(parsed) + __import__("datetime").timedelta(days=i)
        for i in span
        if (min(parsed) + __import__("datetime").timedelta(days=i)).weekday() < 5
        and min(parsed) + __import__("datetime").timedelta(days=i) not in parsed
    )
    return OnlyTradingCalendar(
        calendar_id=OnlyCalendarId(str(calendar_id)),
        venue_id=OnlyVenueId(venue),
        timezone=OnlyTimeZone("Asia/Shanghai"),
        sessions=(
            OnlyTradingSession("morning", time(9, 30), time(11, 30)),
            OnlyTradingSession("afternoon", time(13), time(15)),
        ),
        holidays=holidays,
    )
