from datetime import UTC, datetime
from decimal import Decimal

import pytest

from onlyalpha.domain.enums import (
    OnlyAssetClass,
    OnlyContractType,
    OnlyMarketType,
)
from onlyalpha.domain.errors import OnlyValidationError
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRawSymbol
from onlyalpha.domain.instrument import OnlyCryptoPerpetual, OnlyEquity
from onlyalpha.domain.value import OnlyCurrency, OnlyPrice, OnlyQuantity


def test_equity_validates_market_precision_increment_and_version(equity: OnlyEquity) -> None:
    assert equity.validates_price(OnlyPrice(Decimal("10.05"), 2))
    assert not equity.validates_price(OnlyPrice(Decimal("10.005"), 3))
    assert equity.validates_quantity(OnlyQuantity(Decimal("101"), 0))
    assert equity.is_effective_at(datetime(2026, 1, 1, tzinfo=UTC))
    assert OnlyEquity.from_json(equity.to_json()) == equity


def test_inverse_and_quanto_contract_currency_constraints(instrument_id: OnlyInstrumentId) -> None:
    btc = OnlyCurrency("BTC", 8)
    usd = OnlyCurrency("USD", 2)
    usdt = OnlyCurrency("USDT", 8)
    common = {
        "instrument_id": instrument_id,
        "raw_symbol": OnlyRawSymbol("BTCUSD-PERP"),
        "market_type": OnlyMarketType.DERIVATIVE,
        "quote_currency": usd,
        "price_precision": 2,
        "quantity_precision": 0,
        "tick_size": OnlyPrice(Decimal("0.50"), 2),
        "step_size": OnlyQuantity(Decimal("1"), 0),
        "base_currency": btc,
        "margin_currency": btc,
    }
    inverse = OnlyCryptoPerpetual(
        **common,
        settlement_currency=btc,
        contract_type=OnlyContractType.INVERSE,
    )
    assert inverse.asset_class is OnlyAssetClass.CRYPTOCURRENCY
    with pytest.raises(OnlyValidationError):
        OnlyCryptoPerpetual(
            **common,
            settlement_currency=usdt,
            contract_type=OnlyContractType.INVERSE,
        )
