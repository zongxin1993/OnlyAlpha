"""Deterministic multi-market instrument fixtures."""

from datetime import UTC, datetime
from decimal import Decimal

from onlyalpha.domain.enums import (
    OnlyAssetClass,
    OnlyContractType,
    OnlyExerciseStyle,
    OnlyMarketType,
    OnlyOptionType,
    OnlySettlementType,
)
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRawSymbol, OnlySymbol, OnlyVenueId
from onlyalpha.domain.instrument import (
    OnlyCryptoPerpetual,
    OnlyCryptoSpot,
    OnlyEquity,
    OnlyETF,
    OnlyFuture,
    OnlyFxPair,
    OnlyInstrument,
    OnlyOption,
)
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyMultiplier, OnlyPrice, OnlyQuantity

EFFECTIVE_FROM = datetime(2020, 1, 1, tzinfo=UTC)


def _id(symbol: str, venue: str) -> OnlyInstrumentId:
    return OnlyInstrumentId(OnlySymbol(symbol), OnlyVenueId(venue))


def _cash_common(
    symbol: str,
    venue: str,
    currency: OnlyCurrency,
    quantity_precision: int,
    step: str,
    lot: str,
) -> dict[str, object]:
    return {
        "instrument_id": _id(symbol, venue),
        "raw_symbol": OnlyRawSymbol(symbol),
        "market_type": OnlyMarketType.CASH,
        "quote_currency": currency,
        "settlement_currency": currency,
        "price_precision": 2,
        "quantity_precision": quantity_precision,
        "tick_size": OnlyPrice(Decimal("0.01"), 2),
        "step_size": OnlyQuantity(Decimal(step), quantity_precision),
        "lot_size": OnlyQuantity(Decimal(lot), quantity_precision),
        "effective_from": EFFECTIVE_FROM,
        "timezone": "UTC",
    }


def build_instruments() -> dict[str, OnlyInstrument]:
    cny = OnlyCurrency("CNY", 2)
    hkd = OnlyCurrency("HKD", 2)
    usd = OnlyCurrency("USD", 2)
    usdt = OnlyCurrency("USDT", 8)
    btc = OnlyCurrency("BTC", 8)
    eur = OnlyCurrency("EUR", 2)
    a_share = OnlyEquity(**_cash_common("600000", "XSHG", cny, 0, "1", "100"))  # type: ignore[arg-type]
    etf = OnlyETF(**_cash_common("510300", "XSHG", cny, 0, "1", "100"))  # type: ignore[arg-type]
    hk = OnlyEquity(**_cash_common("0700", "XHKG", hkd, 0, "1", "100"))  # type: ignore[arg-type]
    us = OnlyEquity(**_cash_common("AAPL", "XNAS", usd, 3, "0.001", "0.001"))  # type: ignore[arg-type]
    future = OnlyFuture(
        instrument_id=_id("IF2606", "CFFEX"),
        raw_symbol=OnlyRawSymbol("IF2606"),
        asset_class=OnlyAssetClass.INDEX,
        market_type=OnlyMarketType.DERIVATIVE,
        quote_currency=cny,
        settlement_currency=cny,
        margin_currency=cny,
        price_precision=1,
        quantity_precision=0,
        tick_size=OnlyPrice(Decimal("0.2"), 1),
        step_size=OnlyQuantity(Decimal("1"), 0),
        contract_multiplier=OnlyMultiplier(Decimal("300"), 0),
        underlying=_id("000300", "XSHG"),
        expiration_time=datetime(2026, 6, 19, tzinfo=UTC),
        last_trade_time=datetime(2026, 6, 19, tzinfo=UTC),
        settlement_type=OnlySettlementType.CASH,
        effective_from=EFFECTIVE_FROM,
    )
    option = OnlyOption(
        instrument_id=_id("AAPL260619C00200000", "XNAS"),
        raw_symbol=OnlyRawSymbol("AAPL-CALL"),
        asset_class=OnlyAssetClass.EQUITY,
        market_type=OnlyMarketType.DERIVATIVE,
        quote_currency=usd,
        settlement_currency=usd,
        margin_currency=usd,
        price_precision=2,
        quantity_precision=0,
        tick_size=OnlyPrice(Decimal("0.01"), 2),
        step_size=OnlyQuantity(Decimal("1"), 0),
        contract_multiplier=OnlyMultiplier(Decimal("100"), 0),
        underlying=us.instrument_id,
        strike_price=OnlyPrice(Decimal("200.00"), 2),
        expiration_time=datetime(2026, 6, 19, tzinfo=UTC),
        option_type=OnlyOptionType.CALL,
        exercise_style=OnlyExerciseStyle.AMERICAN,
        settlement_type=OnlySettlementType.PHYSICAL,
        effective_from=EFFECTIVE_FROM,
    )
    fx_fields = _cash_common("EURUSD", "OTC", usd, 0, "1000", "1000")
    fx_fields.update({"tick_size": OnlyPrice(Decimal("0.0001"), 4), "price_precision": 4})
    fx = OnlyFxPair(**fx_fields, base_currency=eur)  # type: ignore[arg-type]
    spot = OnlyCryptoSpot(
        **_cash_common("BTCUSDT", "BINANCE", usdt, 6, "0.000001", "0.000001"),  # type: ignore[arg-type]
        base_currency=btc,
        minimum_notional=OnlyMoney(Decimal("10.00000000"), usdt),
    )
    linear = OnlyCryptoPerpetual(
        instrument_id=_id("BTCUSDT-PERP", "BINANCE"),
        raw_symbol=OnlyRawSymbol("BTCUSDT"),
        market_type=OnlyMarketType.DERIVATIVE,
        base_currency=btc,
        quote_currency=usdt,
        settlement_currency=usdt,
        margin_currency=usdt,
        price_precision=2,
        quantity_precision=0,
        tick_size=OnlyPrice(Decimal("0.01"), 2),
        step_size=OnlyQuantity(Decimal("1"), 0),
        contract_type=OnlyContractType.LINEAR,
        effective_from=EFFECTIVE_FROM,
    )
    inverse = OnlyCryptoPerpetual(
        instrument_id=_id("BTCUSD-PERP", "BYBIT"),
        raw_symbol=OnlyRawSymbol("BTCUSD"),
        market_type=OnlyMarketType.DERIVATIVE,
        base_currency=btc,
        quote_currency=usd,
        settlement_currency=btc,
        margin_currency=btc,
        price_precision=2,
        quantity_precision=0,
        tick_size=OnlyPrice(Decimal("0.50"), 2),
        step_size=OnlyQuantity(Decimal("1"), 0),
        contract_type=OnlyContractType.INVERSE,
        effective_from=EFFECTIVE_FROM,
    )
    return {
        "a_share": a_share,
        "a_share_etf": etf,
        "hong_kong_equity": hk,
        "us_fractional": us,
        "china_future": future,
        "option": option,
        "fx_pair": fx,
        "crypto_spot": spot,
        "linear_perpetual": linear,
        "inverse_perpetual": inverse,
    }
