from collections.abc import Mapping
from datetime import date, time, timedelta
from decimal import Decimal
from typing import Any

from onlyalpha_plugin_cn_ashare import OnlyCnAshareInstrumentReference

from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import OnlyMarketType
from onlyalpha.domain.identifiers import OnlyCalendarId, OnlyInstrumentId, OnlyRawSymbol, OnlyVenueId
from onlyalpha.domain.instrument import OnlyEquity, OnlyETF, OnlyIndex, OnlyInstrument
from onlyalpha.domain.time import OnlyTimeZone
from onlyalpha.domain.value import OnlyCurrency, OnlyMultiplier, OnlyPrice, OnlyQuantity

from ..mapping.exchange import to_xt_symbol


def ashare_reference(raw: Mapping[str, object]) -> OnlyCnAshareInstrumentReference:
    """Normalize a frozen, explicitly enriched MiniQMT reference payload.

    MiniQMT instrument detail alone does not prove historical board/ST,
    suspension, or previous-close authority; callers must provide all fields.
    """

    try:
        return OnlyCnAshareInstrumentReference.from_mapping(
            {
                "instrument_id": raw.get("instrument_id"),
                "exchange": raw.get("exchange"),
                "security_type": raw.get("security_type"),
                "board": raw.get("board"),
                "lot_size": raw.get("MinLimitOrderVolume"),
                "price_tick": raw.get("PriceTick"),
                "st_status": raw.get("st_status"),
                "suspended": raw.get("suspended"),
                "previous_close": raw.get("preClose"),
                "effective_from": raw.get("trading_day"),
                "effective_to": raw.get("effective_to"),
                "source": "MINIQMT",
                "source_version": raw.get("source_version"),
                "data_version": raw.get("data_version"),
            }
        )
    except ValueError as exc:
        raise ValueError(f"MINIQMT_REFERENCE_INVALID: {exc}") from exc


def instrument(xtdata: Any, instrument_id: OnlyInstrumentId) -> OnlyInstrument | None:
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


def calendar(xtdata: Any, calendar_id: OnlyCalendarId) -> OnlyTradingCalendar:
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
        min(parsed) + timedelta(days=i)
        for i in span
        if (min(parsed) + timedelta(days=i)).weekday() < 5 and min(parsed) + timedelta(days=i) not in parsed
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
