"""Strict Binance payload interpretation into plugin-owned immutable semantics."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from onlyalpha_market_binance_spot.capability import (
    OnlyBinanceSpotCompatibilityStatus,
    OnlyBinanceSpotOrderGroupCapability,
    only_map_order_type,
    only_map_time_in_force,
)
from onlyalpha_market_binance_spot.reference import (
    OnlyBinanceSpotReference,
    OnlyBinanceSpotReferenceAuthority,
    OnlyBinanceSpotRule,
)

from onlyalpha.plugin.api import OnlyInstrumentId
from onlyalpha_plugin_binance.errors import OnlyBinanceSchemaError
from onlyalpha_plugin_binance.spot.reference.dto import OnlyBinanceSpotExchangeInfo, OnlyBinanceSpotExecutionRules

_FILTER_CATEGORY = {
    "PRICE_FILTER": "STATIC",
    "LOT_SIZE": "STATIC",
    "MIN_NOTIONAL": "STATIC",
    "NOTIONAL": "STATIC",
    "MARKET_LOT_SIZE": "ORDER_TYPE_SPECIFIC",
    "PERCENT_PRICE": "DYNAMIC",
    "PERCENT_PRICE_BY_SIDE": "DYNAMIC",
    "TRAILING_DELTA": "DYNAMIC",
    "ICEBERG_PARTS": "CAPACITY",
    "MAX_NUM_ORDERS": "CAPACITY",
    "MAX_NUM_ALGO_ORDERS": "CAPACITY",
    "MAX_NUM_ICEBERG_ORDERS": "CAPACITY",
    "MAX_POSITION": "CAPACITY",
    "MAX_NUM_ORDER_LISTS": "CAPACITY",
    "MAX_NUM_ORDER_AMENDS": "CAPACITY",
    "T_PLUS_SELL": "SETTLEMENT",
}
_KNOWN_ORDER_TYPES = {
    "LIMIT",
    "MARKET",
    "STOP_LOSS",
    "STOP_LOSS_LIMIT",
    "TAKE_PROFIT",
    "TAKE_PROFIT_LIMIT",
    "LIMIT_MAKER",
}
_KNOWN_STP_MODES = {"NONE", "EXPIRE_MAKER", "EXPIRE_TAKER", "EXPIRE_BOTH", "DECREMENT", "TRANSFER"}


def _decimal(value: object, label: str) -> Decimal:
    if not isinstance(value, str):
        raise OnlyBinanceSchemaError(f"{label}_QUOTED_DECIMAL_REQUIRED")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise OnlyBinanceSchemaError(f"{label}_DECIMAL_INVALID") from exc


def _canonical_value(value: object) -> str | bool | int:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return str(Decimal(value))
        except InvalidOperation:
            return value
    raise OnlyBinanceSchemaError("BINANCE_RULE_VALUE_INVALID")


def only_normalize_binance_spot_reference(
    exchange_payload: bytes, execution_payload: bytes, *, observed_at: datetime, raw_fingerprints: tuple[str, ...]
) -> OnlyBinanceSpotReferenceAuthority:
    exchange = OnlyBinanceSpotExchangeInfo.parse(exchange_payload).raw
    execution = OnlyBinanceSpotExecutionRules.parse(execution_payload).raw
    execution_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for item in execution["symbolRules"]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("symbol"), str)
            or not isinstance(item.get("rules"), list)
        ):
            raise OnlyBinanceSchemaError("EXECUTION_RULE_SYMBOL_INVALID")
        execution_by_symbol[item["symbol"]] = item["rules"]
    references = tuple(
        _symbol(item, execution_by_symbol.get(item.get("symbol"), []), observed_at, raw_fingerprints)
        for item in exchange["symbols"]
    )
    if not references:
        raise OnlyBinanceSchemaError("BINANCE_SPOT_SYMBOLS_EMPTY")
    return OnlyBinanceSpotReferenceAuthority.create(references)


def _symbol(
    raw: object, execution: list[dict[str, Any]], observed_at: datetime, raw_fingerprints: tuple[str, ...]
) -> OnlyBinanceSpotReference:
    if not isinstance(raw, dict):
        raise OnlyBinanceSchemaError("SYMBOL_OBJECT_REQUIRED")
    required = (
        "symbol",
        "status",
        "baseAsset",
        "quoteAsset",
        "orderTypes",
        "filters",
        "isSpotTradingAllowed",
        "permissionSets",
        "defaultSelfTradePreventionMode",
        "allowedSelfTradePreventionModes",
    )
    if any(name not in raw for name in required):
        raise OnlyBinanceSchemaError("SYMBOL_REQUIRED_FIELD_MISSING")
    symbol = raw["symbol"]
    if not all(isinstance(raw[name], str) for name in ("symbol", "status", "baseAsset", "quoteAsset")):
        raise OnlyBinanceSchemaError("SYMBOL_TEXT_FIELD_INVALID")
    compatible = raw["status"] in {"TRADING", "HALT", "BREAK"}
    if not isinstance(raw["orderTypes"], list):
        raise OnlyBinanceSchemaError("ORDER_TYPES_INVALID")
    for value in raw["orderTypes"]:
        if not isinstance(value, str):
            raise OnlyBinanceSchemaError("ORDER_TYPE_INVALID")
        if value not in _KNOWN_ORDER_TYPES:
            compatible = False
        else:
            only_map_order_type(value)
    filters: dict[str, dict[str, Any]] = {}
    rules: list[OnlyBinanceSpotRule] = []
    for item in raw["filters"]:
        if not isinstance(item, dict) or not isinstance(item.get("filterType"), str):
            raise OnlyBinanceSchemaError("FILTER_INVALID")
        kind = item["filterType"]
        category = _FILTER_CATEGORY.get(kind)
        if category is None:
            compatible = False
            category = "UNKNOWN_CRITICAL"
        if kind in filters:
            raise OnlyBinanceSchemaError("FILTER_DUPLICATE")
        filters[kind] = item
        rules.append(
            OnlyBinanceSpotRule(
                kind, category, tuple(sorted((k, _canonical_value(v)) for k, v in item.items() if k != "filterType"))
            )
        )
    for item in execution:
        kind = item.get("ruleType") if isinstance(item, dict) else None
        if kind != "PRICE_RANGE":
            compatible = False
            category = "UNKNOWN_CRITICAL"
        else:
            category = "DYNAMIC"
        if not isinstance(item, dict) or not isinstance(kind, str):
            raise OnlyBinanceSchemaError("EXECUTION_RULE_INVALID")
        rules.append(
            OnlyBinanceSpotRule(
                kind, category, tuple(sorted((k, _canonical_value(v)) for k, v in item.items() if k != "ruleType"))
            )
        )
    if not execution:
        compatible = False
    price, lot = filters.get("PRICE_FILTER"), filters.get("LOT_SIZE")
    if price is None or lot is None:
        raise OnlyBinanceSchemaError("REQUIRED_STATIC_FILTER_MISSING")
    market_lot = filters.get("MARKET_LOT_SIZE")
    notional = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL")
    permission_sets = raw["permissionSets"]
    if not isinstance(permission_sets, list) or not all(
        isinstance(x, list) and all(isinstance(y, str) for y in x) for x in permission_sets
    ):
        raise OnlyBinanceSchemaError("PERMISSION_SETS_INVALID")
    stp = raw["allowedSelfTradePreventionModes"]
    if (
        not isinstance(stp, list)
        or not all(isinstance(x, str) for x in stp)
        or raw["defaultSelfTradePreventionMode"] not in stp
    ):
        raise OnlyBinanceSchemaError("STP_MODES_INVALID")
    if any(item not in _KNOWN_STP_MODES for item in stp):
        compatible = False
    capability_names = (
        "quoteOrderQtyMarketAllowed",
        "allowTrailingStop",
        "cancelReplaceAllowed",
        "amendAllowed",
        "pegInstructionsAllowed",
    )
    if any(name in raw and not isinstance(raw[name], bool) for name in capability_names):
        raise OnlyBinanceSchemaError("CAPABILITY_BOOLEAN_INVALID")
    capabilities = tuple(sorted((name, bool(raw.get(name, False))) for name in capability_names))
    groups = tuple(
        group.value
        for field, group in (
            ("ocoAllowed", OnlyBinanceSpotOrderGroupCapability.OCO),
            ("otoAllowed", OnlyBinanceSpotOrderGroupCapability.OTO),
            ("opoAllowed", OnlyBinanceSpotOrderGroupCapability.OPO),
        )
        if raw.get(field) is True
    )
    return OnlyBinanceSpotReference.create(
        instrument_id=OnlyInstrumentId.parse(f"{symbol}.BINANCE"),
        raw_symbol=symbol,
        base_currency=raw["baseAsset"],
        quote_currency=raw["quoteAsset"],
        provider_status=raw["status"],
        spot_trading_allowed=raw["isSpotTradingAllowed"],
        price_tick=_decimal(price["tickSize"], "TICK_SIZE"),
        minimum_price=_decimal(price["minPrice"], "MIN_PRICE") or None,
        maximum_price=_decimal(price["maxPrice"], "MAX_PRICE") or None,
        quantity_step=_decimal(lot["stepSize"], "STEP_SIZE"),
        minimum_quantity=_decimal(lot["minQty"], "MIN_QTY"),
        maximum_quantity=_decimal(lot["maxQty"], "MAX_QTY") or None,
        market_quantity_step=None if market_lot is None else _decimal(market_lot["stepSize"], "MARKET_STEP_SIZE"),
        market_minimum_quantity=None if market_lot is None else _decimal(market_lot["minQty"], "MARKET_MIN_QTY"),
        market_maximum_quantity=None
        if market_lot is None
        else (_decimal(market_lot["maxQty"], "MARKET_MAX_QTY") or None),
        minimum_notional=None if notional is None else _decimal(notional.get("minNotional"), "MIN_NOTIONAL"),
        maximum_notional=None
        if notional is None or "maxNotional" not in notional
        else (_decimal(notional["maxNotional"], "MAX_NOTIONAL") or None),
        venue_order_types=tuple(sorted(raw["orderTypes"])),
        time_in_force=tuple(item.value for item in map(only_map_time_in_force, ("GTC", "IOC", "FOK"))),
        order_group_capabilities=groups,
        default_stp_mode=raw["defaultSelfTradePreventionMode"],
        allowed_stp_modes=tuple(sorted(stp)),
        permission_sets=tuple(tuple(sorted(x)) for x in permission_sets),
        capabilities=capabilities,
        rules=tuple(sorted(rules)),
        source_raw_fingerprints=tuple(sorted(raw_fingerprints)),
        compatibility_status=OnlyBinanceSpotCompatibilityStatus.COMPATIBLE
        if compatible
        else OnlyBinanceSpotCompatibilityStatus.INCOMPATIBLE,
        observed_at=observed_at,
    )
