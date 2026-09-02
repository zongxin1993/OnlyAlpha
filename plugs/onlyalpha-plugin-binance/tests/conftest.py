from decimal import Decimal

import pytest

from onlyalpha.domain.enums import (
    OnlyAggregationSource,
    OnlyAssetClass,
    OnlyBarAggregation,
    OnlyCurrencyType,
    OnlyInstrumentType,
    OnlyMarketType,
    OnlyPriceType,
)
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRawSymbol
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.market import OnlyBarSpecification, OnlyBarType
from onlyalpha.domain.value import OnlyCurrency, OnlyPrice, OnlyQuantity


@pytest.fixture
def binance_bar_type() -> tuple[OnlyInstrument, OnlyBarType]:
    instrument_id = OnlyInstrumentId.parse("BTCUSDT.BINANCE")
    usdt = OnlyCurrency("USDT", 2, OnlyCurrencyType.CRYPTO)
    instrument = OnlyInstrument(
        instrument_id=instrument_id,
        raw_symbol=OnlyRawSymbol("BTCUSDT"),
        asset_class=OnlyAssetClass.CRYPTOCURRENCY,
        instrument_type=OnlyInstrumentType.CRYPTO_SPOT,
        market_type=OnlyMarketType.CASH,
        quote_currency=usdt,
        settlement_currency=usdt,
        base_currency=OnlyCurrency("BTC", 8, OnlyCurrencyType.CRYPTO),
        price_precision=2,
        quantity_precision=0,
        tick_size=OnlyPrice(Decimal("0.01"), 2),
        step_size=OnlyQuantity(Decimal("1"), 0),
    )
    return instrument, OnlyBarType(
        instrument_id,
        OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
        OnlyAggregationSource.EXTERNAL,
    )
