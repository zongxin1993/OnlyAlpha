"""Credential-bounded deterministic Binance private REST transport."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from onlyalpha_plugin_binance.errors import OnlyBinanceError


class OnlyBinanceDispatchKnowledge(StrEnum):
    NOT_DISPATCHED = "NOT_DISPATCHED"
    KNOWN_RESULT = "KNOWN_RESULT"
    UNKNOWN = "UNKNOWN"


class OnlyBinancePrivateRequestError(OnlyBinanceError):
    def __init__(self, code: str, knowledge: OnlyBinanceDispatchKnowledge) -> None:
        super().__init__(code)
        self.code = code
        self.knowledge = knowledge


@dataclass(frozen=True, slots=True, repr=False)
class OnlyBinanceCredentials:
    api_key: str
    secret_key: str

    def __post_init__(self) -> None:
        if not self.api_key or not self.secret_key or any(value.isspace() for value in (self.api_key, self.secret_key)):
            raise ValueError("BINANCE_CREDENTIALS_INVALID")

    def __repr__(self) -> str:
        return "OnlyBinanceCredentials(api_key=<redacted>, secret_key=<redacted>)"


@dataclass(frozen=True, slots=True)
class OnlyBinanceHttpResponse:
    status: int
    headers: Mapping[str, str]
    payload: bytes


class OnlyBinancePrivateTransport(Protocol):
    def __call__(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> OnlyBinanceHttpResponse: ...


def only_binance_hmac_sha256(secret_key: str, query: str) -> str:
    return hmac.new(secret_key.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()


def _urllib_transport(
    method: str,
    url: str,
    headers: Mapping[str, str],
    timeout_seconds: float,
    max_response_bytes: int,
) -> OnlyBinanceHttpResponse:
    request = Request(url, headers=dict(headers), method=method)
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 -- base URL is HTTPS-validated
            payload = bytes(response.read(max_response_bytes + 1))
            status = int(response.status)
            response_headers = dict(response.headers.items())
    except HTTPError as exc:
        payload = bytes(exc.read(max_response_bytes + 1))
        status = int(exc.code)
        response_headers = dict(exc.headers.items()) if exc.headers is not None else {}
    except (URLError, TimeoutError, OSError) as exc:
        raise OnlyBinancePrivateRequestError(
            f"BINANCE_PRIVATE_REQUEST_UNKNOWN: {type(exc).__name__}",
            OnlyBinanceDispatchKnowledge.UNKNOWN,
        ) from exc
    if len(payload) > max_response_bytes:
        raise OnlyBinancePrivateRequestError(
            "BINANCE_PRIVATE_RESPONSE_TOO_LARGE",
            OnlyBinanceDispatchKnowledge.KNOWN_RESULT,
        )
    return OnlyBinanceHttpResponse(status, response_headers, payload)


class OnlyBinancePrivateHttpClient:
    def __init__(
        self,
        base_url: str,
        credentials: OnlyBinanceCredentials,
        timestamp_ms: Callable[[], int],
        *,
        recv_window_ms: int = 5_000,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 8 * 1024 * 1024,
        transport: OnlyBinancePrivateTransport = _urllib_transport,
        response_observer: Callable[[str, str, int, bytes], None] | None = None,
    ) -> None:
        if (
            not base_url.startswith("https://")
            or not 1 <= recv_window_ms <= 60_000
            or timeout_seconds <= 0
            or timeout_seconds > 30
            or max_response_bytes <= 0
        ):
            raise ValueError("BINANCE_PRIVATE_HTTP_CONFIGURATION_INVALID")
        self._base_url = base_url.rstrip("/")
        self._credentials = credentials
        self._timestamp_ms = timestamp_ms
        self._recv_window_ms = recv_window_ms
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._transport = transport
        self._response_observer = response_observer or (lambda _method, _path, _status, _payload: None)

    def request_json(
        self,
        method: str,
        path: str,
        parameters: Mapping[str, str] | None = None,
        *,
        signed: bool = True,
    ) -> bytes:
        if method not in {"GET", "POST", "DELETE", "PUT"} or not path.startswith("/"):
            raise ValueError("BINANCE_PRIVATE_REQUEST_INVALID")
        canonical = dict(parameters or {})
        if signed:
            canonical["recvWindow"] = str(self._recv_window_ms)
            timestamp = self._timestamp_ms()
            if timestamp < 0:
                raise ValueError("BINANCE_TIMESTAMP_INVALID")
            canonical["timestamp"] = str(timestamp)
        query = urlencode(sorted(canonical.items()))
        if signed:
            signature = only_binance_hmac_sha256(self._credentials.secret_key, query)
            query = f"{query}&signature={signature}"
        url = self._base_url + path + (f"?{query}" if query else "")
        try:
            response = self._transport(
                method,
                url,
                {"Accept": "application/json", "X-MBX-APIKEY": self._credentials.api_key},
                self._timeout_seconds,
                self._max_response_bytes,
            )
        except OnlyBinancePrivateRequestError:
            raise
        except Exception as exc:
            raise OnlyBinancePrivateRequestError(
                f"BINANCE_PRIVATE_REQUEST_UNKNOWN: {type(exc).__name__}",
                OnlyBinanceDispatchKnowledge.UNKNOWN,
            ) from exc
        self._response_observer(method, path, response.status, response.payload)
        try:
            decoded = json.loads(response.payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise OnlyBinancePrivateRequestError(
                "BINANCE_PRIVATE_RESPONSE_NOT_JSON",
                OnlyBinanceDispatchKnowledge.KNOWN_RESULT,
            ) from exc
        if not isinstance(decoded, (dict, list)):
            raise OnlyBinancePrivateRequestError(
                "BINANCE_PRIVATE_RESPONSE_SHAPE_INVALID",
                OnlyBinanceDispatchKnowledge.KNOWN_RESULT,
            )
        if response.status < 200 or response.status >= 300:
            provider_code = decoded.get("code") if isinstance(decoded, dict) else None
            safe_code = str(provider_code) if isinstance(provider_code, int | str) else "UNKNOWN"
            raise OnlyBinancePrivateRequestError(
                f"BINANCE_PRIVATE_KNOWN_ERROR: {safe_code}",
                OnlyBinanceDispatchKnowledge.KNOWN_RESULT,
            )
        return response.payload


__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("only_")]
