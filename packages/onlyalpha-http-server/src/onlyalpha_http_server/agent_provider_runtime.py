"""Authenticated internal authority for exact Agent Provider runtime resolution."""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from onlyalpha_agent_orchestrator.provider_integration import (
    OnlyAgentModelProfileV1,
    OnlyAgentProviderRuntimeResolverV1,
    OnlyAgentSessionProviderBindingV1,
    OnlyResolvedAgentProviderRuntimeV1,
)


def create_agent_provider_runtime_router(
    resolver: OnlyAgentProviderRuntimeResolverV1,
    bearer_token: str,
) -> APIRouter:
    if not bearer_token:
        raise ValueError("AGENT_PROVIDER_AUTHORITY_CONFIG_INVALID")
    router = APIRouter(prefix="/internal/v1/agent-provider-runtime")

    @router.post("/admit-new", include_in_schema=False)
    async def admit_new(request: Request) -> JSONResponse:
        if not _authorized(request, bearer_token):
            return _error(401, "AGENT_PROVIDER_AUTHORITY_UNAUTHORIZED")
        try:
            payload = await _payload(request, {"schema_version", "model_profile"})
            profile = OnlyAgentModelProfileV1.from_dict(_mapping(payload["model_profile"]))
            return JSONResponse(_response(resolver.admit_new(profile)))
        except Exception as error:
            code = getattr(error, "code", None)
            if not isinstance(code, str):
                return _error(409, "AGENT_PROVIDER_AUTHORITY_ADMISSION_DENIED")
            status = (
                503
                if code
                in {
                    "INTEGRATION_RUNTIME_IMPLEMENTATION_UNAVAILABLE",
                    "INTEGRATION_RUNTIME_PERSISTENCE_UNAVAILABLE",
                    "INTEGRATION_RUNTIME_SECRET_UNAVAILABLE",
                }
                else 409
            )
            return _error(status, code)

    @router.post("/continue-exact", include_in_schema=False)
    async def continue_exact(request: Request) -> JSONResponse:
        if not _authorized(request, bearer_token):
            return _error(401, "AGENT_PROVIDER_AUTHORITY_UNAUTHORIZED")
        try:
            payload = await _payload(
                request,
                {"schema_version", "session_provider_binding", "model_profile"},
            )
            binding = OnlyAgentSessionProviderBindingV1.from_dict(_mapping(payload["session_provider_binding"]))
            profile = OnlyAgentModelProfileV1.from_dict(_mapping(payload["model_profile"]))
            return JSONResponse(_response(resolver.continue_exact(binding, profile)))
        except Exception:
            return _error(409, "AGENT_WORKFLOW_RUNTIME_MISMATCH")

    return router


def _authorized(request: Request, expected: str) -> bool:
    value = request.headers.get("Authorization", "")
    return value.startswith("Bearer ") and secrets.compare_digest(value[7:], expected)


async def _payload(request: Request, expected: set[str]) -> Mapping[str, object]:
    payload = await request.json()
    if not isinstance(payload, dict) or set(payload) != expected or payload.get("schema_version") != 1:
        raise ValueError
    return cast(Mapping[str, object], payload)


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError
    return cast(Mapping[str, object], value)


def _response(runtime: OnlyResolvedAgentProviderRuntimeV1) -> dict[str, object]:
    endpoint = runtime.endpoint
    return {
        "schema_version": 1,
        "provider_binding": runtime.binding.to_dict(),
        "model_profile": runtime.model_profile.to_dict(),
        "endpoint": {
            "base_url": endpoint.base_url,
            "api_credential": endpoint.api_credential,
            "expected_provider_id": endpoint.expected_provider_id,
            "expected_model_id": endpoint.expected_model_id,
            "expected_model_version": endpoint.expected_model_version,
            "connect_timeout_seconds": endpoint.connect_timeout_seconds,
            "read_timeout_seconds": endpoint.read_timeout_seconds,
            "verify_tls": endpoint.verify_tls,
        },
    }


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code}}, status_code=status)


__all__ = ["create_agent_provider_runtime_router"]
