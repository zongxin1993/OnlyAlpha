from datetime import UTC, datetime
from decimal import Decimal

import pytest

from onlyalpha.domain.enums import OnlyMarketType
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRawSymbol, OnlySymbol, OnlyVenueId
from onlyalpha.domain.instrument import OnlyEquity
from onlyalpha.domain.value import OnlyCurrency, OnlyMultiplier, OnlyPrice, OnlyQuantity


@pytest.fixture
def cny() -> OnlyCurrency:
    return OnlyCurrency("CNY", 2)


@pytest.fixture
def instrument_id() -> OnlyInstrumentId:
    return OnlyInstrumentId(OnlySymbol("600000"), OnlyVenueId("XSHG"))


@pytest.fixture
def equity(cny: OnlyCurrency, instrument_id: OnlyInstrumentId) -> OnlyEquity:
    return OnlyEquity(
        instrument_id=instrument_id,
        raw_symbol=OnlyRawSymbol("600000"),
        market_type=OnlyMarketType.CASH,
        quote_currency=cny,
        settlement_currency=cny,
        price_precision=2,
        quantity_precision=0,
        tick_size=OnlyPrice(Decimal("0.01"), 2),
        step_size=OnlyQuantity(Decimal("1"), 0),
        contract_multiplier=OnlyMultiplier(Decimal("1"), 0),
        lot_size=OnlyQuantity(Decimal("100"), 0),
        effective_from=datetime(2020, 1, 1, tzinfo=UTC),
    )
