"""Authenticated private HTTP contract for the independently deployed Agent node."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import APIRouter, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict

from onlyalpha.research.agent.errors import OnlyAgentContextError
from onlyalpha.research.agent.model import OnlyAgentResearchBriefV1

from .coordination import OnlyAgentSessionExecutionBusy
from .node_service import OnlyAgentNodeControlServiceV1


class _StrictDto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class AgentSessionAdmissionRequestDto(_StrictDto):
    research_brief: dict[str, object]


class AgentSessionAdmissionResponseDto(_StrictDto):
    schema_version: Literal[1] = 1
    session_fingerprint: str
    research_brief_fingerprint: str
    session_disposition: str
    workflow_implementation_fingerprint: str


class AgentSessionAdvanceResponseDto(_StrictDto):
    schema_version: Literal[1] = 1
    session_fingerprint: str
    derived_status: str
    next_action_kind: str | None
    failure_code: str | None


class AgentNodeHealthDto(_StrictDto):
    status: Literal["ALIVE", "READY", "NOT_READY"]


def create_agent_node_app(
    service: OnlyAgentNodeControlServiceV1,
    *,
    control_bearer_token: str,
    readiness: Callable[[], bool],
) -> FastAPI:
    if not control_bearer_token:
        raise ValueError("AGENT_INTERNAL_CONTROL_CREDENTIAL_INVALID")
    accepting = True

    @asynccontextmanager
    async def lifespan(_app: FastAPI):  # type: ignore[no-untyped-def]
        nonlocal accepting
        accepting = True
        yield
        accepting = False

    app = FastAPI(title="OnlyAlpha Agent Node Private API", version="1", lifespan=lifespan)
    router = APIRouter(prefix="/internal/v1")

    def authorize(authorization: Annotated[str | None, Header()] = None) -> None:
        expected = f"Bearer {control_bearer_token}"
        if authorization is None or not secrets.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="AGENT_INTERNAL_CONTROL_UNAUTHORIZED")
        if not accepting:
            raise HTTPException(status_code=503, detail="AGENT_NODE_DRAINING")

    @router.get("/healthz", response_model=AgentNodeHealthDto)
    def health() -> AgentNodeHealthDto:
        return AgentNodeHealthDto(status="ALIVE")

    @router.get("/readyz", response_model=AgentNodeHealthDto)
    def ready() -> AgentNodeHealthDto:
        if not accepting or not readiness():
            raise HTTPException(status_code=503, detail="AGENT_NODE_NOT_READY")
        return AgentNodeHealthDto(status="READY")

    @router.post("/sessions", response_model=AgentSessionAdmissionResponseDto)
    def admit(
        request: AgentSessionAdmissionRequestDto,
        authorization: Annotated[str | None, Header()] = None,
    ) -> AgentSessionAdmissionResponseDto:
        authorize(authorization)
        try:
            brief = OnlyAgentResearchBriefV1.from_dict(request.research_brief)
            outcome = service.admit_session(brief)
        except OnlyAgentContextError as error:
            raise HTTPException(status_code=409, detail=error.code) from error
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=400, detail="AGENT_SESSION_ADMISSION_INVALID") from error
        return AgentSessionAdmissionResponseDto(
            session_fingerprint=outcome.session_fingerprint,
            research_brief_fingerprint=outcome.research_brief_fingerprint,
            session_disposition=outcome.session_disposition.value,
            workflow_implementation_fingerprint=outcome.workflow_implementation_fingerprint,
        )

    @router.post("/sessions/{session_fingerprint}/advance", response_model=AgentSessionAdvanceResponseDto)
    def advance(
        session_fingerprint: str, authorization: Annotated[str | None, Header()] = None
    ) -> AgentSessionAdvanceResponseDto:
        authorize(authorization)
        try:
            state = service.advance_once(session_fingerprint)
        except OnlyAgentSessionExecutionBusy as error:
            raise HTTPException(status_code=409, detail="AGENT_SESSION_BUSY") from error
        except OnlyAgentContextError as error:
            raise HTTPException(status_code=409, detail=error.code) from error
        return AgentSessionAdvanceResponseDto(
            session_fingerprint=state.agent_session_fingerprint,
            derived_status=state.status.value,
            next_action_kind=None if state.next_action is None else state.next_action.action_kind.value,
            failure_code=state.failure_code,
        )

    app.include_router(router)
    return app


__all__ = [name for name in globals() if name.startswith(("Agent", "create_"))]
