"""Thin Product facade over the generated OpenAPI transport projection."""

from __future__ import annotations

from collections.abc import Mapping
from types import TracebackType
from typing import Self, cast
from urllib.parse import quote

import httpx

from ._protocol import admit_schema
from .errors import OnlyAlphaApiError, OnlyAlphaProtocolError, OnlyAlphaTransportError
from .generated.contract import (
    OPERATIONS,
    JSONValue,
    ResearchRunDto,
    ResearchRunPageDto,
    SubmitResearchRunResponse,
)


class _HttpBoundary:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float,
        headers: Mapping[str, str] | None,
        transport: httpx.Client | None,
    ) -> None:
        normalized = base_url.rstrip("/")
        if not normalized:
            raise ValueError("base_url must not be empty")
        self.base_url = normalized
        self._owns_transport = transport is None
        self._transport = httpx.Client(timeout=timeout, headers=dict(headers or {})) if transport is None else transport

    def close(self) -> None:
        if self._owns_transport:
            self._transport.close()

    def request(
        self,
        operation_id: str,
        *,
        path_values: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str | int] | None = None,
        json: object | None = None,
    ) -> object:
        operation = cast(Mapping[str, object], OPERATIONS[operation_id])
        path = cast(str, operation["path"])
        for name, value in (path_values or {}).items():
            path = path.replace("{" + name + "}", quote(value, safe=""))
        try:
            response = self._transport.request(
                cast(str, operation["method"]),
                f"{self.base_url}{path}",
                headers=headers,
                params=params,
                json=json,
            )
        except (httpx.TransportError, OSError) as exc:
            raise OnlyAlphaTransportError("OnlyAlpha Product API is unavailable") from exc
        try:
            body = response.json()
        except (TypeError, ValueError) as exc:
            raise OnlyAlphaProtocolError("Product API response is not valid JSON") from exc
        success_status = cast(int, operation["success_status"])
        if response.status_code != success_status:
            if not isinstance(body, dict) or not isinstance(body.get("error"), dict):
                raise OnlyAlphaProtocolError("Product API error response violates the governed contract")
            error = body["error"]
            if not isinstance(error.get("code"), str) or not isinstance(error.get("detail"), str):
                raise OnlyAlphaProtocolError("Product API error response violates the governed contract")
            phase = error.get("phase")
            if phase is not None and not isinstance(phase, str):
                raise OnlyAlphaProtocolError("Product API error response violates the governed contract")
            raise OnlyAlphaApiError(
                status_code=response.status_code,
                code=error["code"],
                detail=error["detail"],
                phase=phase,
                request_id=response.headers.get("X-Request-ID"),
            )
        response_schema = cast(str, operation["response_schema"])
        admit_schema(response_schema, body)
        return body


class OnlyAlphaResearchClient:
    def __init__(self, boundary: _HttpBoundary) -> None:
        self._boundary = boundary

    def create(
        self,
        *,
        specification: Mapping[str, JSONValue],
        idempotency_key: str,
    ) -> SubmitResearchRunResponse:
        body = self._boundary.request(
            "submit_run_api_v2_research_runs_post",
            headers={"Idempotency-Key": idempotency_key},
            json={"specification": dict(specification)},
        )
        return cast(SubmitResearchRunResponse, body)

    def get(self, run_id: str) -> ResearchRunDto:
        body = self._boundary.request(
            "get_run_api_v2_research_runs__run_id__get",
            path_values={"run_id": run_id},
        )
        return cast(ResearchRunDto, body)

    def list(self, *, limit: int = 50, cursor: str | None = None) -> ResearchRunPageDto:
        params: dict[str, str | int] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        body = self._boundary.request("list_runs_api_v2_research_runs_get", params=params)
        return cast(ResearchRunPageDto, body)

    def cancel(self, run_id: str, *, idempotency_key: str | None = None) -> ResearchRunDto:
        headers = None if idempotency_key is None else {"Idempotency-Key": idempotency_key}
        body = self._boundary.request(
            "cancel_run_api_v2_research_runs__run_id__cancellation_post",
            path_values={"run_id": run_id},
            headers=headers,
        )
        return cast(ResearchRunDto, body)


class OnlyAlphaClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout: float = 10.0,
        headers: Mapping[str, str] | None = None,
        transport: httpx.Client | None = None,
    ) -> None:
        self._boundary = _HttpBoundary(
            base_url,
            timeout=timeout,
            headers=headers,
            transport=transport,
        )
        self.research = OnlyAlphaResearchClient(self._boundary)

    def close(self) -> None:
        self._boundary.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


__all__ = ["OnlyAlphaClient", "OnlyAlphaResearchClient"]
