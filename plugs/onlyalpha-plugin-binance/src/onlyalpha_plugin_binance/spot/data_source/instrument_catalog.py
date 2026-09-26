"""Binance Spot public reference projection into canonical OnlyAlpha instruments."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from onlyalpha.domain.enums import (
    OnlyAssetClass,
    OnlyCurrencyType,
    OnlyInstrumentType,
    OnlyMarketType,
    OnlySecurityStatus,
)
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRawSymbol
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.value import OnlyCurrency, OnlyPrice, OnlyQuantity
from onlyalpha.plugin.data_source import (
    OnlyDataSourceInstrumentCatalogRequestV1,
    OnlyDataSourceInstrumentV1,
)
from onlyalpha_plugin_binance.common.http import OnlyBinancePublicHttpClient
from onlyalpha_plugin_binance.errors import OnlyBinanceError

from ..reference.dto import OnlyBinanceSpotExchangeInfo
from .config import OnlyBinanceSpotDataSourceConfig

MARKET = "SPOT"
VENUE = "BINANCE"
MARKET_DATA_CAPABILITIES = ("BAR_1M_EXTERNAL_RAW",)
# W1 historical closure intentionally bounds the first reference universe instead of
# downloading the full Spot catalogue for every text query. Expanding it is a later
# product slice, not an implicit side effect of a search.
REFERENCE_SYMBOLS = ("BTCUSDT", "ETHUSDT")

_STATUS = {
    "TRADING": OnlySecurityStatus.ACTIVE,
    "HALT": OnlySecurityStatus.HALTED,
    "BREAK": OnlySecurityStatus.HALTED,
}


def only_binance_spot_instrument(raw: Mapping[str, object]) -> OnlyInstrument:
    """Project one exchangeInfo symbol into a canonical market-data instrument."""

    symbol = _text(raw.get("symbol"), "SYMBOL")
    quote = _text(raw.get("quoteAsset"), "QUOTE_ASSET")
    base = _text(raw.get("baseAsset"), "BASE_ASSET")
    filters = raw.get("filters")
    if not isinstance(filters, list):
        raise OnlyBinanceError("BINANCE_EXCHANGE_INFO_FILTERS_INVALID")
    price = _filter(filters, "PRICE_FILTER")
    lot = _filter(filters, "LOT_SIZE")
    tick = _decimal(price.get("tickSize"), "TICK_SIZE")
    step = _decimal(lot.get("stepSize"), "STEP_SIZE")
    price_precision = _precision(tick)
    quantity_precision = _precision(step)
    tick = _quantize(tick, price_precision)
    step = _quantize(step, quantity_precision)
    status = _STATUS.get(str(raw.get("status")), OnlySecurityStatus.SUSPENDED)
    quote_currency = OnlyCurrency(quote, price_precision, OnlyCurrencyType.CRYPTO)
    return OnlyInstrument(
        instrument_id=OnlyInstrumentId.parse(f"{symbol}.{VENUE}"),
        raw_symbol=OnlyRawSymbol(symbol),
        asset_class=OnlyAssetClass.CRYPTOCURRENCY,
        instrument_type=OnlyInstrumentType.CRYPTO_SPOT,
        market_type=OnlyMarketType.CASH,
        quote_currency=quote_currency,
        settlement_currency=quote_currency,
        base_currency=OnlyCurrency(base, quantity_precision, OnlyCurrencyType.CRYPTO),
        price_precision=price_precision,
        quantity_precision=quantity_precision,
        tick_size=OnlyPrice(tick, price_precision),
        step_size=OnlyQuantity(step, quantity_precision),
        minimum_quantity=OnlyQuantity(
            _quantize(_decimal(lot.get("minQty"), "MIN_QTY"), quantity_precision), quantity_precision
        ),
        status=status,
        timezone="UTC",
    )


@dataclass(frozen=True, slots=True)
class OnlyBinanceSpotInstrumentCatalog:
    """Bounded provider reference lookup; the venue remains the symbol authority.

    Lookups are confined to `REFERENCE_SYMBOLS`, so an unapproved symbol can never
    silently expand the admitted W1 instrument universe.
    """

    def list_instruments(
        self, request: OnlyDataSourceInstrumentCatalogRequestV1
    ) -> tuple[OnlyDataSourceInstrumentV1, ...]:
        config = request.plugin_config
        if not isinstance(config, OnlyBinanceSpotDataSourceConfig):
            raise OnlyBinanceError("BINANCE_PLUGIN_CONFIG_INVALID")
        http = OnlyBinancePublicHttpClient(
            config.endpoints.rest_base_url,
            timeout_seconds=config.timeout_seconds,
            max_response_bytes=config.max_response_bytes,
        )
        if request.instrument_ids:
            requested = {only_binance_raw_symbol(item) for item in request.instrument_ids}
            symbols = tuple(sorted(requested & set(REFERENCE_SYMBOLS)))
            if not symbols:
                return ()
            payload = http.get_json("/api/v3/exchangeInfo", {"symbols": _symbols_parameter(symbols)})
            projected = tuple(only_binance_spot_projection(item) for item in _symbols(payload))
            return tuple(sorted(projected, key=lambda item: str(item.instrument.instrument_id))[: request.limit])
        query = request.query.strip().upper()
        if not query:
            # No search criteria: the provider catalogue is never dumped implicitly.
            return ()
        symbols = tuple(item for item in REFERENCE_SYMBOLS if query in item)
        if not symbols:
            return ()
        payload = http.get_json("/api/v3/exchangeInfo", {"symbols": _symbols_parameter(symbols)})
        return tuple(
            sorted(
                (only_binance_spot_projection(item) for item in _symbols(payload)),
                key=lambda item: str(item.instrument.instrument_id),
            )[: request.limit]
        )


def only_binance_raw_symbol(instrument_id: str) -> str:
    symbol, _, venue = instrument_id.rpartition(".")
    if not symbol or venue != VENUE:
        raise OnlyBinanceError("BINANCE_INSTRUMENT_ID_INVALID")
    return symbol.upper()


def only_binance_spot_projection(raw: Mapping[str, object]) -> OnlyDataSourceInstrumentV1:
    instrument = only_binance_spot_instrument(raw)
    return OnlyDataSourceInstrumentV1(
        instrument,
        str(instrument.raw_symbol),
        VENUE,
        MARKET,
        MARKET_DATA_CAPABILITIES,
    )


def _symbols(payload: bytes) -> tuple[Mapping[str, object], ...]:
    raw = OnlyBinanceSpotExchangeInfo.parse(payload).raw["symbols"]
    if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
        raise OnlyBinanceError("BINANCE_EXCHANGE_INFO_SYMBOLS_INVALID")
    return tuple(raw)


def _symbols_parameter(symbols: tuple[str, ...]) -> str:
    return json.dumps(list(symbols), separators=(",", ":"))


def _filter(filters: Sequence[object], filter_type: str) -> Mapping[str, object]:
    matches = [item for item in filters if isinstance(item, dict) and item.get("filterType") == filter_type]
    if len(matches) != 1:
        raise OnlyBinanceError(f"BINANCE_EXCHANGE_INFO_{filter_type}_INVALID")
    return matches[0]


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OnlyBinanceError(f"BINANCE_EXCHANGE_INFO_{label}_INVALID")
    return value.strip()


def _decimal(value: object, label: str) -> Decimal:
    if not isinstance(value, str):
        raise OnlyBinanceError(f"BINANCE_EXCHANGE_INFO_{label}_INVALID")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise OnlyBinanceError(f"BINANCE_EXCHANGE_INFO_{label}_INVALID") from exc
    if parsed <= 0:
        raise OnlyBinanceError(f"BINANCE_EXCHANGE_INFO_{label}_INVALID")
    return parsed


def _precision(value: Decimal) -> int:
    exponent = value.normalize().as_tuple().exponent
    return max(0, -int(exponent)) if isinstance(exponent, int) else 0


def _quantize(value: Decimal, precision: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-precision))


__all__ = [
    "MARKET",
    "MARKET_DATA_CAPABILITIES",
    "REFERENCE_SYMBOLS",
    "VENUE",
    "OnlyBinanceSpotInstrumentCatalog",
    "only_binance_raw_symbol",
    "only_binance_spot_instrument",
    "only_binance_spot_projection",
]
