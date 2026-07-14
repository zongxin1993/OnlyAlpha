from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from onlyalpha.domain.enums import OnlyMarketType, OnlyOffset, OnlyOrderSide, OnlyOrderType, OnlyTimeInForce
from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyInstrumentId,
    OnlyOrderRequestId,
    OnlyRawSymbol,
    OnlySymbol,
    OnlyVenueId,
)
from onlyalpha.domain.instrument import OnlyEquity
from onlyalpha.domain.value import OnlyCurrency, OnlyMultiplier, OnlyPrice, OnlyQuantity


@pytest.fixture
def cny() -> OnlyCurrency:
    return OnlyCurrency("CNY", 2)


@pytest.fixture
def instrument_id() -> OnlyInstrumentId:
    return OnlyInstrumentId(OnlySymbol("TEST"), OnlyVenueId("XTEST"))


@pytest.fixture
def equity(cny: OnlyCurrency, instrument_id: OnlyInstrumentId) -> OnlyEquity:
    return OnlyEquity(
        instrument_id=instrument_id,
        raw_symbol=OnlyRawSymbol("TEST"),
        market_type=OnlyMarketType.CASH,
        quote_currency=cny,
        settlement_currency=cny,
        price_precision=2,
        quantity_precision=0,
        tick_size=OnlyPrice(Decimal("0.05"), 2),
        step_size=OnlyQuantity(Decimal("1"), 0),
        contract_multiplier=OnlyMultiplier(Decimal("1"), 0),
        effective_from=datetime(2020, 1, 1, tzinfo=UTC),
        effective_to=datetime(2025, 1, 1, tzinfo=UTC),
    )


@pytest.fixture
def buy_request(instrument_id: OnlyInstrumentId) -> OnlyOrderRequest:
    return OnlyOrderRequest(
        OnlyOrderRequestId("request"),
        instrument_id,
        OnlyOrderSide.BUY,
        OnlyOrderType.LIMIT,
        OnlyQuantity(Decimal("2"), 0),
        OnlyTimeInForce.DAY,
        account_id=OnlyAccountId("account"),
        offset=OnlyOffset.NONE,
        price=OnlyPrice(Decimal("10.00"), 2),
    )


@pytest.fixture
def equity_versions(equity: OnlyEquity) -> tuple[OnlyEquity, OnlyEquity]:
    second = replace(
        equity,
        tick_size=OnlyPrice(Decimal("0.01"), 2),
        lot_size=OnlyQuantity(Decimal("1"), 0),
        instrument_version=2,
        effective_from=datetime(2025, 1, 1, tzinfo=UTC),
        effective_to=None,
    )
    return equity, second
