"""Provider DTO interpretation into Market Product-owned normalized authorities."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from onlyalpha_plugin_binance_usdm import (
    OnlyBinanceUsdmAccountReferenceAuthority,
    OnlyBinanceUsdmAccountTradingReference,
    OnlyBinanceUsdmFundingScheduleReference,
    OnlyBinanceUsdmPublicMarketReference,
    OnlyBinanceUsdmPublicReferenceAuthority,
)

from onlyalpha.domain.enums import OnlyMarginMode
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.trading import OnlyPositionMode, OnlyReferencePriceKind
from onlyalpha.identity import only_identity_fingerprint
from onlyalpha.market.economics import OnlyAccountEffectiveTradingInputs, OnlyMarginRequirementSegment
from onlyalpha_plugin_binance.errors import OnlyBinanceSchemaError

from .dto import (
    OnlyBinanceUsdmAccountProfileDto,
    OnlyBinanceUsdmExchangeInfoDto,
    OnlyBinanceUsdmFundingInfoDto,
    OnlyBinanceUsdmLeverageBracketDto,
)

NORMALIZER_VERSION = "BINANCE_USDM_REFERENCE_NORMALIZER@2"
PROVIDER_SCHEMA_VERSION = "BINANCE_USDM_FAPI_REFERENCE@2026-09-01"
DEFAULT_FUNDING_SEMANTIC_VERSION = "BINANCE_USDM_DEFAULT_FUNDING_INTERVAL@2026-09-01"


def _decimal(value: object, code: str) -> Decimal:
    if not isinstance(value, str):
        raise OnlyBinanceSchemaError(code)
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise OnlyBinanceSchemaError(code) from exc
    if not result.is_finite():
        raise OnlyBinanceSchemaError(code)
    return result


def _integer(value: object, code: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise OnlyBinanceSchemaError(code)
    return value


def only_normalize_binance_usdm_references(
    exchange_info: bytes,
    funding_info: bytes,
    leverage_brackets: bytes,
    account_profile: bytes,
    *,
    observed_at: datetime,
    published_at: datetime,
    coverage_start: datetime,
    coverage_end: datetime | None,
    raw_fingerprints: tuple[str, str, str, str],
) -> tuple[OnlyBinanceUsdmPublicReferenceAuthority, OnlyBinanceUsdmAccountReferenceAuthority]:
    exchange = OnlyBinanceUsdmExchangeInfoDto.parse(exchange_info).raw
    funding = OnlyBinanceUsdmFundingInfoDto.parse(funding_info).raw
    brackets = OnlyBinanceUsdmLeverageBracketDto.parse(leverage_brackets).raw
    account = OnlyBinanceUsdmAccountProfileDto.parse(account_profile).raw
    funding_by_symbol = _unique_by_symbol(funding, "FUNDING_INFO")
    bracket_by_symbol = _unique_by_symbol(brackets, "LEVERAGE_BRACKET")
    account_symbols = _unique_by_symbol(account["symbols"], "ACCOUNT_PROFILE")
    position_mode = OnlyPositionMode(str(account["positionMode"]))
    public_references: list[OnlyBinanceUsdmPublicMarketReference] = []
    account_references: list[OnlyBinanceUsdmAccountTradingReference] = []
    provider_revision = str(exchange.get("serverTime", "UNVERSIONED"))
    for raw_symbol in exchange["symbols"]:
        if not isinstance(raw_symbol, dict):
            raise OnlyBinanceSchemaError("BINANCE_USDM_SYMBOL_SCHEMA_INVALID")
        symbol = raw_symbol.get("symbol")
        if not isinstance(symbol, str) or symbol not in bracket_by_symbol or symbol not in account_symbols:
            raise OnlyBinanceSchemaError("BINANCE_USDM_REQUIRED_SYMBOL_AUTHORITY_MISSING")
        if raw_symbol.get("contractType") != "PERPETUAL":
            raise OnlyBinanceSchemaError("BINANCE_USDM_CONTRACT_TYPE_UNSUPPORTED")
        filters = _filters(raw_symbol.get("filters"))
        price_filter = filters.get("PRICE_FILTER")
        lot_filter = filters.get("LOT_SIZE")
        notional_filter = filters.get("MIN_NOTIONAL")
        if price_filter is None or lot_filter is None or notional_filter is None:
            raise OnlyBinanceSchemaError("BINANCE_USDM_REQUIRED_FILTER_MISSING")
        funding_adjustment = funding_by_symbol.get(symbol)
        interval_hours = (
            8
            if funding_adjustment is None
            else _integer(funding_adjustment.get("fundingIntervalHours"), "BINANCE_USDM_FUNDING_INTERVAL_INVALID")
        )
        funding_semantic_version = (
            DEFAULT_FUNDING_SEMANTIC_VERSION
            if funding_adjustment is None
            else f"BINANCE_USDM_FUNDING_INFO@{provider_revision}"
        )
        instrument_id = OnlyInstrumentId.parse(f"{symbol}-PERP.BINANCE")
        public_references.append(
            OnlyBinanceUsdmPublicMarketReference.create(
                instrument_id=instrument_id,
                raw_symbol=symbol,
                provider_status=_text(raw_symbol, "status"),
                settlement_currency=_text(raw_symbol, "marginAsset"),
                contract_multiplier=Decimal(1),
                price_tick=_decimal(price_filter.get("tickSize"), "BINANCE_USDM_TICK_SIZE_INVALID"),
                minimum_price=_optional_positive(price_filter.get("minPrice"), "BINANCE_USDM_MIN_PRICE_INVALID"),
                maximum_price=_optional_positive(price_filter.get("maxPrice"), "BINANCE_USDM_MAX_PRICE_INVALID"),
                quantity_step=_decimal(lot_filter.get("stepSize"), "BINANCE_USDM_STEP_SIZE_INVALID"),
                minimum_quantity=_decimal(lot_filter.get("minQty"), "BINANCE_USDM_MIN_QTY_INVALID"),
                maximum_quantity=_optional_positive(lot_filter.get("maxQty"), "BINANCE_USDM_MAX_QTY_INVALID"),
                minimum_notional=_optional_positive(
                    notional_filter.get("notional"), "BINANCE_USDM_MIN_NOTIONAL_INVALID"
                ),
                funding_schedule=OnlyBinanceUsdmFundingScheduleReference(
                    interval_hours * 60 * 60,
                    0,
                    OnlyReferencePriceKind.MARK,
                    funding_semantic_version,
                ),
                coverage_start=coverage_start,
                coverage_end=coverage_end,
                observed_at=observed_at,
                published_at=published_at,
                provider_revision=provider_revision,
                normalizer_semantic_version=NORMALIZER_VERSION,
                provider_schema_semantic_version=PROVIDER_SCHEMA_VERSION,
                source_raw_fingerprints=raw_fingerprints[:2],
            )
        )
        account_raw = account_symbols[symbol]
        margin_mode = OnlyMarginMode(_text(account_raw, "marginMode"))
        leverage = _decimal(account_raw.get("leverage"), "BINANCE_USDM_ACCOUNT_LEVERAGE_INVALID")
        account_source = only_identity_fingerprint(raw_fingerprints[2:])
        effective_inputs = OnlyAccountEffectiveTradingInputs(position_mode, margin_mode, leverage, account_source)
        segments = _margin_segments(bracket_by_symbol[symbol], leverage)
        account_references.append(
            OnlyBinanceUsdmAccountTradingReference.create(
                instrument_id=instrument_id,
                effective_inputs=effective_inputs,
                margin_segments=segments,
                coverage_start=coverage_start,
                coverage_end=coverage_end,
                observed_at=observed_at,
                provider_revision=provider_revision,
                normalizer_semantic_version=NORMALIZER_VERSION,
                provider_schema_semantic_version=PROVIDER_SCHEMA_VERSION,
                source_raw_fingerprints=raw_fingerprints[2:],
            )
        )
    if not public_references:
        raise OnlyBinanceSchemaError("BINANCE_USDM_SYMBOLS_EMPTY")
    return (
        OnlyBinanceUsdmPublicReferenceAuthority.create(tuple(public_references)),
        OnlyBinanceUsdmAccountReferenceAuthority.create(tuple(account_references)),
    )


def _unique_by_symbol(values: object, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(values, list):
        raise OnlyBinanceSchemaError(f"BINANCE_USDM_{label}_LIST_REQUIRED")
    result: dict[str, dict[str, Any]] = {}
    for item in values:
        if not isinstance(item, dict) or not isinstance(item.get("symbol"), str):
            raise OnlyBinanceSchemaError(f"BINANCE_USDM_{label}_SYMBOL_INVALID")
        if item["symbol"] in result:
            raise OnlyBinanceSchemaError(f"BINANCE_USDM_{label}_SYMBOL_DUPLICATE")
        result[item["symbol"]] = item
    return result


def _filters(value: object) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        raise OnlyBinanceSchemaError("BINANCE_USDM_FILTERS_INVALID")
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("filterType"), str):
            raise OnlyBinanceSchemaError("BINANCE_USDM_FILTER_INVALID")
        kind = item["filterType"]
        if kind in result:
            raise OnlyBinanceSchemaError("BINANCE_USDM_FILTER_DUPLICATE")
        result[kind] = item
    known = {
        "PRICE_FILTER",
        "LOT_SIZE",
        "MARKET_LOT_SIZE",
        "MAX_NUM_ORDERS",
        "MAX_NUM_ALGO_ORDERS",
        "MIN_NOTIONAL",
        "PERCENT_PRICE",
    }
    unknown = set(result) - known
    if unknown:
        raise OnlyBinanceSchemaError(f"BINANCE_USDM_FILTER_UNSUPPORTED:{sorted(unknown)[0]}")
    return result


def _margin_segments(raw: dict[str, Any], leverage: Decimal) -> tuple[OnlyMarginRequirementSegment, ...]:
    values = raw.get("brackets")
    if not isinstance(values, list) or not values:
        raise OnlyBinanceSchemaError("BINANCE_USDM_MARGIN_BRACKETS_INVALID")
    coefficient_raw = raw.get("notionalCoef", "1")
    coefficient = Decimal(str(coefficient_raw))
    segments: list[OnlyMarginRequirementSegment] = []
    for item in values:
        if not isinstance(item, dict):
            raise OnlyBinanceSchemaError("BINANCE_USDM_MARGIN_BRACKET_INVALID")
        maximum_leverage = Decimal(_integer(item.get("initialLeverage"), "BINANCE_USDM_BRACKET_LEVERAGE_INVALID"))
        if leverage > maximum_leverage:
            raise OnlyBinanceSchemaError("BINANCE_USDM_EFFECTIVE_LEVERAGE_EXCEEDS_BRACKET")
        lower = _decimal(item.get("notionalFloor"), "BINANCE_USDM_NOTIONAL_FLOOR_INVALID") * coefficient
        upper_value = _decimal(item.get("notionalCap"), "BINANCE_USDM_NOTIONAL_CAP_INVALID") * coefficient
        maintenance = _decimal(item.get("maintMarginRatio"), "BINANCE_USDM_MAINTENANCE_RATE_INVALID")
        cumulative = _decimal(item.get("cum"), "BINANCE_USDM_CUM_INVALID") * coefficient
        segments.append(
            OnlyMarginRequirementSegment(
                lower,
                upper_value,
                Decimal(1) / leverage,
                Decimal(0),
                maintenance,
                -cumulative,
            )
        )
    return tuple(segments)


def _text(raw: dict[str, Any], name: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value:
        raise OnlyBinanceSchemaError(f"BINANCE_USDM_{name.upper()}_INVALID")
    return value


def _optional_positive(value: object, code: str) -> Decimal | None:
    result = _decimal(value, code)
    return result if result > 0 else None


__all__ = ["only_normalize_binance_usdm_references"]
