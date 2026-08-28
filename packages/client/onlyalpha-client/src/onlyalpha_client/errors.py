"""Stable transport-facing errors; business exceptions remain server-owned."""

from __future__ import annotations


class OnlyAlphaClientError(Exception):
    """Base class for failures observed at the Product client boundary."""


class OnlyAlphaTransportError(OnlyAlphaClientError):
    """The HTTP exchange did not produce a response."""


class OnlyAlphaProtocolError(OnlyAlphaClientError):
    """The server response did not conform to the governed public contract."""


class OnlyAlphaApiError(OnlyAlphaClientError):
    """A contract-shaped non-success response returned by the Product API."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        detail: str,
        phase: str | None = None,
        request_id: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.detail = detail
        self.phase = phase
        self.request_id = request_id
        super().__init__(f"{status_code} {code}: {detail}")


__all__ = [name for name in globals() if name.startswith("OnlyAlpha")]
