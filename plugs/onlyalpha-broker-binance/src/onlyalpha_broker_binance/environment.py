"""Endpoints for the private Binance Spot API."""

from enum import StrEnum


class OnlyBinanceBrokerEnvironment(StrEnum):
    LIVE = "LIVE"
    SPOT_TESTNET = "SPOT_TESTNET"

    @property
    def rest_base_url(self) -> str:
        return "https://api.binance.com" if self is self.LIVE else "https://testnet.binance.vision"

    @property
    def websocket_api_base_url(self) -> str:
        return (
            "wss://ws-api.binance.com:443/ws-api/v3"
            if self is self.LIVE
            else "wss://ws-api.testnet.binance.vision/ws-api/v3"
        )
