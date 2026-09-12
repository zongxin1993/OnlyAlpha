"""Non-authoritative public gateway to the private Agent node contract."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Annotated, Literal, Protocol, cast
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.agent.model import OnlyAgentResearchBriefV1

AGENT_GATEWAY_ROUTE_TAG = "agent-gateway"


class _StrictDto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class AgentSessionRequestDto(_StrictDto):
    research_brief: dict[str, object]


class AgentSessionResponseDto(_StrictDto):
    schema_version: Literal[1]
    session_fingerprint: str
    research_brief_fingerprint: str
    session_disposition: str
    workflow_implementation_fingerprint: str


class AgentAdvanceResponseDto(_StrictDto):
    schema_version: Literal[1]
    session_fingerprint: str
    derived_status: str
    next_action_kind: str | None
    failure_code: str | None


class OnlyAgentNodeGateway(Protocol):
    def post_json_verified(self, path: str, payload: Mapping[str, object]) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class OnlyAgentNodeGatewayConfigV1:
    base_url: str
    bearer_token: str = field(repr=False)
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not self.bearer_token
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("AGENT_NODE_GATEWAY_CONFIG_INVALID")
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


class OnlyAgentNodeHttpGatewayV1:
    def __init__(self, config: OnlyAgentNodeGatewayConfigV1) -> None:
        self._config = config
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def post_json_verified(self, path: str, payload: Mapping[str, object]) -> Mapping[str, object]:
        if not path.startswith("/internal/v1/") or "?" in path or "#" in path:
            raise ValueError("AGENT_NODE_GATEWAY_PATH_INVALID")
        request = urllib.request.Request(
            self._config.base_url + path,
            data=only_canonical_json(payload).encode(),
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._config.bearer_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=self._config.timeout_seconds) as response:
                raw = response.read()
                if response.status != 200 or response.headers.get_content_type() != "application/json":
                    raise ValueError("AGENT_NODE_GATEWAY_RESPONSE_INVALID")
        except urllib.error.HTTPError as error:
            if error.code in {400, 401, 404, 409}:
                raise HTTPException(status_code=error.code, detail="AGENT_REQUEST_REJECTED") from error
            raise HTTPException(status_code=503, detail="AGENT_NODE_UNAVAILABLE") from error
        except (OSError, urllib.error.URLError) as error:
            raise HTTPException(status_code=503, detail="AGENT_NODE_UNAVAILABLE") from error
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise HTTPException(status_code=502, detail="AGENT_NODE_RESPONSE_INVALID") from error
        if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
            raise HTTPException(status_code=502, detail="AGENT_NODE_RESPONSE_INVALID")
        return cast(Mapping[str, object], value)


SessionPath = Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")]


def create_agent_gateway_router(gateway: OnlyAgentNodeGateway) -> APIRouter:
    router = APIRouter(prefix="/api/v2/agent", tags=[AGENT_GATEWAY_ROUTE_TAG])

    @router.post("/sessions", operation_id="admit_agent_session_v2", response_model=AgentSessionResponseDto)
    def admit(request: AgentSessionRequestDto) -> AgentSessionResponseDto:
        try:
            brief = OnlyAgentResearchBriefV1.from_dict(request.research_brief)
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=400, detail="AGENT_RESEARCH_BRIEF_INVALID") from error
        payload = gateway.post_json_verified("/internal/v1/sessions", {"research_brief": brief.to_dict()})
        try:
            return AgentSessionResponseDto.model_validate(payload)
        except PydanticValidationError as error:
            raise HTTPException(status_code=502, detail="AGENT_NODE_RESPONSE_INVALID") from error

    @router.post(
        "/sessions/{session_fingerprint}/advance",
        operation_id="advance_agent_session_once_v2",
        response_model=AgentAdvanceResponseDto,
    )
    def advance(session_fingerprint: SessionPath) -> AgentAdvanceResponseDto:
        payload = gateway.post_json_verified(
            f"/internal/v1/sessions/{quote(session_fingerprint, safe='')}/advance",
            {},
        )
        try:
            return AgentAdvanceResponseDto.model_validate(payload)
        except PydanticValidationError as error:
            raise HTTPException(status_code=502, detail="AGENT_NODE_RESPONSE_INVALID") from error

    return router


__all__ = [name for name in globals() if name.startswith(("Agent", "Only", "create_"))]
