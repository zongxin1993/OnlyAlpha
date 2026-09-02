"""Explicit USD-M public reference HTTP contracts."""

from onlyalpha_plugin_binance.common.http import OnlyBinancePublicHttpClient


class OnlyBinanceUsdmReferenceClient:
    def __init__(self, http: OnlyBinancePublicHttpClient) -> None:
        self._http = http

    def exchange_info(self) -> bytes:
        return self._http.get_json("/fapi/v1/exchangeInfo")

    def funding_info(self) -> bytes:
        return self._http.get_json("/fapi/v1/fundingInfo")


__all__ = ["OnlyBinanceUsdmReferenceClient"]
