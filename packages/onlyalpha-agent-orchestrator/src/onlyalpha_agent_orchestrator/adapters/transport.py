"""Single-request raw HTTP transport with explicit dispatch ambiguity."""

from __future__ import annotations

import http.client
import ssl
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlsplit

from ..runtime import OnlyAgentExternalIoPermit, assert_external_io_permit


class OnlyHttpDispatchClassification(StrEnum):
    DEFINITE_NOT_DISPATCHED = "DEFINITE_NOT_DISPATCHED"
    RESPONSE_RECEIVED = "RESPONSE_RECEIVED"
    POSSIBLY_DISPATCHED_RESPONSE_UNAVAILABLE = "POSSIBLY_DISPATCHED_RESPONSE_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class OnlyHttpRequestV1:
    method: str
    url: str
    headers: MappingProxyType[str, str] = field(repr=False)
    body: bytes

    def __post_init__(self) -> None:
        parsed = urlsplit(self.url)
        if (
            self.method not in {"DELETE", "GET", "PATCH", "POST", "PUT"}
            or parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or not isinstance(self.headers, MappingProxyType)
            or not isinstance(self.body, bytes)
        ):
            raise ValueError("AGENT_HTTP_REQUEST_INVALID")


@dataclass(frozen=True, slots=True)
class OnlyHttpResponseV1:
    status_code: int
    headers: tuple[tuple[str, str], ...]
    body: bytes

    def header(self, name: str) -> str | None:
        values = tuple(value for key, value in self.headers if key.casefold() == name.casefold())
        return values[0] if len(values) == 1 else None


@dataclass(frozen=True, slots=True)
class OnlyHttpTransportOutcomeV1:
    classification: OnlyHttpDispatchClassification
    response: OnlyHttpResponseV1 | None = None

    def __post_init__(self) -> None:
        complete = self.classification is OnlyHttpDispatchClassification.RESPONSE_RECEIVED
        if complete != (self.response is not None):
            raise ValueError("AGENT_HTTP_OUTCOME_INVALID")


class OnlyRawHttpTransportV1:
    """No redirects, retries, cookies, fallback, pooling, or ambient proxy use."""

    def __init__(
        self,
        *,
        connect_timeout_seconds: float,
        read_timeout_seconds: float,
        verify_tls: bool,
        ca_bundle_path: Path | None,
        maximum_response_bytes: int = 4 * 1024 * 1024,
    ) -> None:
        if connect_timeout_seconds <= 0 or read_timeout_seconds <= 0 or maximum_response_bytes <= 0:
            raise ValueError("AGENT_HTTP_TRANSPORT_CONFIG_INVALID")
        self._connect_timeout = float(connect_timeout_seconds)
        self._read_timeout = float(read_timeout_seconds)
        self._verify_tls = verify_tls
        self._ca_bundle_path = ca_bundle_path
        self._maximum_response_bytes = maximum_response_bytes

    def send(
        self,
        request: OnlyHttpRequestV1,
        permit: OnlyAgentExternalIoPermit,
    ) -> OnlyHttpTransportOutcomeV1:
        assert_external_io_permit(permit, consume=True)
        parsed = urlsplit(request.url)
        if parsed.hostname is None:  # already enforced by OnlyHttpRequestV1
            raise ValueError("AGENT_HTTP_REQUEST_INVALID")
        hostname = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        connection: http.client.HTTPConnection
        if parsed.scheme == "https":
            context = (
                ssl.create_default_context(cafile=None if self._ca_bundle_path is None else str(self._ca_bundle_path))
                if self._verify_tls
                else ssl._create_unverified_context()  # noqa: SLF001 - explicit operator TLS policy
            )
            connection = http.client.HTTPSConnection(
                hostname,
                port,
                timeout=self._connect_timeout,
                context=context,
            )
        else:
            connection = http.client.HTTPConnection(hostname, port, timeout=self._connect_timeout)
        try:
            try:
                connection.connect()
            except (TimeoutError, OSError, ssl.SSLError):
                return OnlyHttpTransportOutcomeV1(OnlyHttpDispatchClassification.DEFINITE_NOT_DISPATCHED)
            if connection.sock is None:  # pragma: no cover - stdlib invariant
                return OnlyHttpTransportOutcomeV1(OnlyHttpDispatchClassification.DEFINITE_NOT_DISPATCHED)
            connection.sock.settimeout(self._read_timeout)
            path = parsed.path or "/"
            if parsed.query:
                path = f"{path}?{parsed.query}"
            try:
                connection.request(request.method, path, body=request.body or None, headers=dict(request.headers))
                response = connection.getresponse()
                body = response.read(self._maximum_response_bytes + 1)
                if len(body) > self._maximum_response_bytes:
                    return OnlyHttpTransportOutcomeV1(
                        OnlyHttpDispatchClassification.POSSIBLY_DISPATCHED_RESPONSE_UNAVAILABLE,
                    )
            except (TimeoutError, OSError, ssl.SSLError, http.client.HTTPException):
                return OnlyHttpTransportOutcomeV1(
                    OnlyHttpDispatchClassification.POSSIBLY_DISPATCHED_RESPONSE_UNAVAILABLE
                )
            result = OnlyHttpResponseV1(response.status, tuple(response.getheaders()), body)
            return OnlyHttpTransportOutcomeV1(OnlyHttpDispatchClassification.RESPONSE_RECEIVED, result)
        finally:
            connection.close()


__all__ = [name for name in globals() if name.startswith("Only")]
