import json

from onlyalpha_plugin_binance.common.http import OnlyBinancePublicHttpClient


class OnlyBinanceSpotReferenceClient:
    def __init__(self, http: OnlyBinancePublicHttpClient) -> None:
        self._http = http

    def ping(self) -> bytes:
        return self._http.get_json("/api/v3/ping")

    def server_time(self) -> bytes:
        return self._http.get_json("/api/v3/time")

    def exchange_info(self, symbols: tuple[str, ...]) -> bytes:
        return self._http.get_json(
            "/api/v3/exchangeInfo", {"symbols": json.dumps(sorted(set(symbols)), separators=(",", ":"))}
        )

    def execution_rules(self, symbols: tuple[str, ...]) -> bytes:
        return self._http.get_json(
            "/api/v3/executionRules", {"symbols": json.dumps(sorted(set(symbols)), separators=(",", ":"))}
        )
