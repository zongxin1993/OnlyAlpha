"""Minimal Binance Spot private REST endpoint client."""

from __future__ import annotations

from collections.abc import Mapping

from onlyalpha.broker.models import OnlyBrokerCancelRequest, OnlyBrokerOrderRequest
from onlyalpha.domain.identifiers import OnlyClientOrderId, OnlyVenueOrderId
from onlyalpha_plugin_binance.common.private_http import OnlyBinancePrivateHttpClient
from onlyalpha_plugin_binance.spot.broker.codec import (
    only_binance_client_order_id,
    only_binance_spot_cancel_parameters,
    only_binance_spot_order_parameters,
)


class OnlyBinanceSpotPrivateRestClient:
    def __init__(self, http: OnlyBinancePrivateHttpClient) -> None:
        self._http = http

    def authenticate_account(self) -> bytes:
        return self._http.request_json("GET", "/api/v3/account", {"omitZeroBalances": "false"})

    def account(self) -> bytes:
        return self.authenticate_account()

    def submit_order(self, request: OnlyBrokerOrderRequest) -> bytes:
        return self._http.request_json(
            "POST",
            "/api/v3/order",
            only_binance_spot_order_parameters(request),
            side_effecting=True,
        )

    def cancel_order(self, request: OnlyBrokerCancelRequest, *, symbol: str) -> bytes:
        return self._http.request_json(
            "DELETE",
            "/api/v3/order",
            only_binance_spot_cancel_parameters(request, symbol),
            side_effecting=True,
        )

    def query_order(
        self,
        *,
        symbol: str,
        client_order_id: OnlyClientOrderId | None = None,
        venue_order_id: OnlyVenueOrderId | None = None,
    ) -> bytes:
        parameters: dict[str, str] = {"symbol": symbol}
        if client_order_id is not None:
            parameters["origClientOrderId"] = only_binance_client_order_id(client_order_id)
        elif venue_order_id is not None:
            parameters["orderId"] = str(venue_order_id)
        else:
            raise ValueError("BINANCE_QUERY_ORDER_ID_REQUIRED")
        return self._http.request_json("GET", "/api/v3/order", parameters)

    def open_orders(self, *, symbol: str | None = None) -> bytes:
        parameters: Mapping[str, str] = {} if symbol is None else {"symbol": symbol}
        return self._http.request_json("GET", "/api/v3/openOrders", parameters)

    def trades(
        self,
        *,
        symbol: str,
        venue_order_id: OnlyVenueOrderId | None = None,
        from_id: int | None = None,
    ) -> bytes:
        parameters = {"symbol": symbol}
        if venue_order_id is not None:
            parameters["orderId"] = str(venue_order_id)
        if from_id is not None:
            if from_id < 0:
                raise ValueError("BINANCE_TRADE_FROM_ID_INVALID")
            parameters["fromId"] = str(from_id)
        return self._http.request_json("GET", "/api/v3/myTrades", parameters)


__all__ = ["OnlyBinanceSpotPrivateRestClient"]
