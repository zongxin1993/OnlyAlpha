from datetime import time
from decimal import Decimal

import pytest

from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import (
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyMarketType,
    OnlyPriceType,
    OnlySessionType,
)
from onlyalpha.domain.identifiers import (
    OnlyCalendarId,
    OnlyInstrumentId,
    OnlyRawSymbol,
    OnlySymbol,
    OnlyVenueId,
)
from onlyalpha.domain.instrument import OnlyEquity
from onlyalpha.domain.market import OnlyBarSpecification, OnlyBarType
from onlyalpha.domain.time import OnlyTimeZone
from onlyalpha.domain.value import OnlyCurrency, OnlyMultiplier, OnlyPrice, OnlyQuantity


@pytest.fixture
def calendar() -> OnlyTradingCalendar:
    return OnlyTradingCalendar(
        OnlyCalendarId("CN_XSHG"),
        OnlyVenueId("XSHG"),
        OnlyTimeZone("Asia/Shanghai"),
        (
            OnlyTradingSession(
                "morning", time(9, 30), time(11, 30), OnlySessionType.CONTINUOUS
            ),
            OnlyTradingSession(
                "afternoon", time(13), time(15), OnlySessionType.CONTINUOUS
            ),
        ),
    )


@pytest.fixture
def instrument() -> OnlyEquity:
    cny = OnlyCurrency("CNY", 2)
    return OnlyEquity(
        instrument_id=OnlyInstrumentId(OnlySymbol("600000"), OnlyVenueId("XSHG")),
        raw_symbol=OnlyRawSymbol("600000"),
        market_type=OnlyMarketType.CASH,
        quote_currency=cny,
        settlement_currency=cny,
        price_precision=4,
        quantity_precision=0,
        tick_size=OnlyPrice(Decimal("0.0001"), 4),
        step_size=OnlyQuantity(Decimal("1"), 0),
        contract_multiplier=OnlyMultiplier(Decimal("1"), 0),
        trading_calendar_id=OnlyCalendarId("CN_XSHG"),
        timezone="Asia/Shanghai",
    )


@pytest.fixture
def bar_type(instrument: OnlyEquity) -> OnlyBarType:
    return OnlyBarType(
        instrument.instrument_id,
        OnlyBarSpecification(1440, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
        OnlyAggregationSource.EXTERNAL,
    )
