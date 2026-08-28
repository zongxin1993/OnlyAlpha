"""Small bounded public JSON transport with no credential surface."""

import json
from collections.abc import Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from onlyalpha_plugin_binance.errors import OnlyBinanceError


class OnlyBinancePublicHttpClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 10.0) -> None:
        if not base_url.startswith("https://") or timeout_seconds <= 0 or timeout_seconds > 30:
            raise ValueError("BINANCE_PUBLIC_HTTP_CONFIGURATION_INVALID")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def get_json(self, path: str, parameters: Mapping[str, str] | None = None) -> bytes:
        query = "" if not parameters else "?" + urlencode(parameters)
        request = Request(self._base_url + path + query, headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=self._timeout) as response:  # noqa: S310 -- URL is constructor-validated HTTPS
                if response.status != 200:
                    raise OnlyBinanceError(f"BINANCE_HTTP_STATUS: {response.status}")
                payload = bytes(response.read())
        except (HTTPError, URLError, TimeoutError) as exc:
            raise OnlyBinanceError(f"BINANCE_PUBLIC_REQUEST_FAILED: {type(exc).__name__}") from exc
        try:
            parsed = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise OnlyBinanceError("BINANCE_PUBLIC_RESPONSE_NOT_JSON") from exc
        if not isinstance(parsed, (dict, list)):
            raise OnlyBinanceError("BINANCE_PUBLIC_RESPONSE_SHAPE_INVALID")
        return payload
