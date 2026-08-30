"""Small bounded public JSON transport with no credential surface."""

import json
from collections.abc import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from onlyalpha_plugin_binance.errors import OnlyBinanceError


class OnlyBinancePublicHttpClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 8 * 1024 * 1024,
        response_observer: Callable[[str, Mapping[str, str], bytes], None] | None = None,
    ) -> None:
        if (
            not base_url.startswith("https://")
            or timeout_seconds <= 0
            or timeout_seconds > 30
            or max_response_bytes <= 0
        ):
            raise ValueError("BINANCE_PUBLIC_HTTP_CONFIGURATION_INVALID")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._response_observer = response_observer or (lambda _path, _parameters, _payload: None)

    def get_json(self, path: str, parameters: Mapping[str, str] | None = None) -> bytes:
        query = "" if not parameters else "?" + urlencode(parameters)
        request = Request(self._base_url + path + query, headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=self._timeout) as response:  # noqa: S310 -- URL is constructor-validated HTTPS
                if response.status != 200:
                    raise OnlyBinanceError(f"BINANCE_HTTP_STATUS: {response.status}")
                content_type = response.headers.get("Content-Type", "")
                media_type = content_type.split(";", 1)[0].strip().lower()
                if media_type != "application/json" and not (
                    media_type.startswith("application/") and media_type.endswith("+json")
                ):
                    raise OnlyBinanceError("BINANCE_PUBLIC_RESPONSE_MEDIA_TYPE_INVALID")
                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    try:
                        declared_length = int(content_length)
                    except ValueError as exc:
                        raise OnlyBinanceError("BINANCE_PUBLIC_CONTENT_LENGTH_INVALID") from exc
                    if declared_length < 0:
                        raise OnlyBinanceError("BINANCE_PUBLIC_CONTENT_LENGTH_INVALID")
                    if declared_length > self._max_response_bytes:
                        raise OnlyBinanceError("BINANCE_PUBLIC_RESPONSE_TOO_LARGE")
                payload = bytes(response.read(self._max_response_bytes + 1))
                if len(payload) > self._max_response_bytes:
                    raise OnlyBinanceError("BINANCE_PUBLIC_RESPONSE_TOO_LARGE")
        except (HTTPError, URLError, TimeoutError) as exc:
            raise OnlyBinanceError(f"BINANCE_PUBLIC_REQUEST_FAILED: {type(exc).__name__}") from exc
        self._response_observer(path, parameters or {}, payload)
        try:
            parsed = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise OnlyBinanceError("BINANCE_PUBLIC_RESPONSE_NOT_JSON") from exc
        if not isinstance(parsed, (dict, list)):
            raise OnlyBinanceError("BINANCE_PUBLIC_RESPONSE_SHAPE_INVALID")
        return payload
