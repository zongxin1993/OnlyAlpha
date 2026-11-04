"""Binance Spot wire encoding; venue details terminate in this plugin."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from decimal import Decimal

from onlyalpha.broker.models import OnlyBrokerCancelRequest, OnlyBrokerOrderRequest
from onlyalpha.domain.enums import OnlyOrderType
from onlyalpha.domain.identifiers import OnlyClientOrderId

_WIRE_CLIENT_ID = re.compile(r"^[A-Za-z0-9._:/-]{1,36}$")


def _decimal(value: Decimal) -> str:
    return format(value, "f")


def only_binance_client_order_id(client_order_id: OnlyClientOrderId) -> str:
    canonical = str(client_order_id)
    if _WIRE_CLIENT_ID.fullmatch(canonical):
        return canonical
    return "oa_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def only_binance_spot_order_parameters(request: OnlyBrokerOrderRequest) -> Mapping[str, str]:
    parameters = {
        "symbol": request.instrument_id.symbol.value,
        "side": request.side.value,
        "type": request.order_type.value,
        "quantity": _decimal(request.quantity.value),
        "newClientOrderId": only_binance_client_order_id(request.client_order_id),
        "newOrderRespType": "ACK",
    }
    if request.order_type is OnlyOrderType.LIMIT:
        if request.price is None:
            raise ValueError("BINANCE_LIMIT_PRICE_REQUIRED")
        parameters["timeInForce"] = request.time_in_force.value
        parameters["price"] = _decimal(request.price.value)
    elif request.order_type is not OnlyOrderType.MARKET:
        raise ValueError("BINANCE_SPOT_ORDER_TYPE_UNSUPPORTED")
    return parameters


def only_binance_spot_cancel_parameters(request: OnlyBrokerCancelRequest, symbol: str) -> Mapping[str, str]:
    parameters = {"symbol": symbol}
    if request.venue_order_id is not None:
        parameters["orderId"] = str(request.venue_order_id)
    elif request.client_order_id is not None:
        parameters["origClientOrderId"] = only_binance_client_order_id(request.client_order_id)
    else:
        raise ValueError("BINANCE_CANCEL_VENUE_ID_OR_CLIENT_ID_REQUIRED")
    return parameters


__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("only_")]
