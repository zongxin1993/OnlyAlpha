"""Private Binance DTO normalization into provider-neutral Broker models."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId
from onlyalpha.broker.models import OnlyBrokerBalanceSnapshot, OnlyBrokerOrderRequest, OnlyBrokerOrderSnapshot
from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.identifiers import OnlyVenueOrderId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha_plugin_binance.errors import OnlyBinanceSchemaError
from onlyalpha_plugin_binance.spot.broker.codec import only_binance_client_order_id
from onlyalpha_plugin_binance.spot.broker.dto import OnlyBinanceSpotAccountDto, OnlyBinanceSpotOrderDto

_STATUS = {
    "NEW": OnlyOrderStatus.ACCEPTED,
    "PARTIALLY_FILLED": OnlyOrderStatus.PARTIALLY_FILLED,
    "FILLED": OnlyOrderStatus.FILLED,
    "CANCELED": OnlyOrderStatus.CANCELLED,
    "PENDING_CANCEL": OnlyOrderStatus.PENDING_CANCEL,
    "REJECTED": OnlyOrderStatus.REJECTED,
    "EXPIRED": OnlyOrderStatus.EXPIRED,
    "EXPIRED_IN_MATCH": OnlyOrderStatus.EXPIRED,
}


def _decimal(raw: object, code: str) -> Decimal:
    if not isinstance(raw, str):
        raise OnlyBinanceSchemaError(f"{code}_QUOTED_DECIMAL_REQUIRED")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise OnlyBinanceSchemaError(f"{code}_DECIMAL_INVALID") from exc
    if not value.is_finite() or value < 0:
        raise OnlyBinanceSchemaError(f"{code}_DECIMAL_INVALID")
    return value


def only_normalize_binance_spot_balances(
    payload: bytes,
    currencies: Mapping[str, OnlyCurrency],
) -> tuple[OnlyBrokerBalanceSnapshot, ...]:
    raw = OnlyBinanceSpotAccountDto.parse(payload).raw
    result: list[OnlyBrokerBalanceSnapshot] = []
    for item in raw["balances"]:
        if not isinstance(item, dict) or not isinstance(item.get("asset"), str):
            raise OnlyBinanceSchemaError("BINANCE_BALANCE_REQUIRED_FIELD_INVALID")
        asset = item["asset"]
        currency = currencies.get(asset)
        if currency is None:
            raise OnlyBinanceSchemaError(f"BINANCE_BALANCE_CURRENCY_UNRESOLVED: {asset}")
        free = OnlyMoney(_decimal(item.get("free"), "BINANCE_BALANCE_FREE"), currency)
        locked = OnlyMoney(_decimal(item.get("locked"), "BINANCE_BALANCE_LOCKED"), currency)
        result.append(OnlyBrokerBalanceSnapshot(currency, free + locked, free, locked))
    return tuple(sorted(result, key=lambda item: item.currency.code))


def only_normalize_binance_spot_order(
    payload: bytes,
    request: OnlyBrokerOrderRequest,
    *,
    gateway_id: OnlyBrokerGatewayId,
    source_sequence: int,
) -> OnlyBrokerOrderSnapshot:
    raw = OnlyBinanceSpotOrderDto.parse(payload).raw
    required = ("symbol", "orderId", "clientOrderId", "price", "origQty", "executedQty", "status", "updateTime")
    if any(name not in raw for name in required):
        raise OnlyBinanceSchemaError("BINANCE_ORDER_REQUIRED_FIELD_MISSING")
    if raw["symbol"] != request.instrument_id.symbol.value:
        raise OnlyBinanceSchemaError("BINANCE_ORDER_SYMBOL_CONFLICT")
    if raw["clientOrderId"] != only_binance_client_order_id(request.client_order_id):
        raise OnlyBinanceSchemaError("BINANCE_CLIENT_ORDER_ID_CONFLICT")
    if _decimal(raw["origQty"], "BINANCE_ORDER_QUANTITY") != request.quantity.value:
        raise OnlyBinanceSchemaError("BINANCE_ORDER_QUANTITY_CONFLICT")
    provider_status = raw["status"]
    if not isinstance(provider_status, str) or provider_status not in _STATUS:
        raise OnlyBinanceSchemaError("BINANCE_ORDER_STATUS_UNSUPPORTED")
    order_id = raw["orderId"]
    updated_ms = raw["updateTime"]
    if not isinstance(order_id, int | str) or isinstance(order_id, bool):
        raise OnlyBinanceSchemaError("BINANCE_VENUE_ORDER_ID_INVALID")
    if not isinstance(updated_ms, int) or isinstance(updated_ms, bool) or updated_ms < 0:
        raise OnlyBinanceSchemaError("BINANCE_ORDER_UPDATE_TIME_INVALID")
    filled = OnlyQuantity(_decimal(raw["executedQty"], "BINANCE_EXECUTED_QUANTITY"), request.quantity.precision)
    price_value = _decimal(raw["price"], "BINANCE_ORDER_PRICE")
    price = None if price_value == 0 else OnlyPrice(price_value, request.price.precision if request.price else 18)
    return OnlyBrokerOrderSnapshot(
        gateway_id,
        request.account_id,
        request.order_id,
        request.client_order_id,
        OnlyVenueOrderId(str(order_id)),
        request.instrument_id,
        request.side,
        request.offset,
        request.order_type,
        request.quantity,
        filled,
        price,
        _STATUS[provider_status],
        request.submitted_at,
        OnlyTimestamp.from_unix_nanos(updated_ms * 1_000_000),
        source_sequence,
    )


__all__ = [name for name in globals() if name.startswith("only_")]
