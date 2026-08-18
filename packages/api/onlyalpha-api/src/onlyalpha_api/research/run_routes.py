"""Thin Research Run command and operational read HTTP adapter."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Response

from onlyalpha.research.command.errors import OnlyResearchCommandError, OnlyResearchCommandPhase
from onlyalpha.research.command.model import OnlyResearchSubmissionKey
from onlyalpha.research.command.query import DEFAULT_RESEARCH_RUN_PAGE_SIZE, OnlyResearchRunQueryService
from onlyalpha.research.command.service import OnlyResearchCommandService
from onlyalpha.research.run.model import OnlyResearchRunId
from onlyalpha.research.specification.model import OnlyResearchSpecification

from .run_schema import (
    ResearchRunDto,
    ResearchRunErrorEnvelopeDto,
    ResearchRunPageDto,
    SubmitResearchRunRequest,
    SubmitResearchRunResponse,
)

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ResearchRunErrorEnvelopeDto} for status in (400, 404, 409, 500, 503)
}
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


def _run_id(value: str) -> OnlyResearchRunId:
    try:
        return OnlyResearchRunId(value)
    except ValueError as exc:
        raise OnlyResearchCommandError(
            OnlyResearchCommandPhase.COMMAND,
            "RESEARCH_RUN_ID_INVALID",
            "Research Run ID must be a canonical UUID4",
        ) from exc


def _submission_key(value: str | None) -> OnlyResearchSubmissionKey:
    try:
        if value is None:
            raise ValueError("missing")
        return OnlyResearchSubmissionKey(value)
    except ValueError as exc:
        raise OnlyResearchCommandError(
            OnlyResearchCommandPhase.COMMAND,
            "RESEARCH_IDEMPOTENCY_KEY_INVALID",
            "Idempotency-Key must be a canonical UUID4",
        ) from exc


def create_run_router(command: OnlyResearchCommandService, query: OnlyResearchRunQueryService) -> APIRouter:
    router = APIRouter(prefix="/api/v2/research/runs", tags=["research-runs"])

    @router.post("", status_code=202, response_model=SubmitResearchRunResponse, responses=_ERROR_RESPONSES)
    def submit_run(
        request: SubmitResearchRunRequest,
        response: Response,
        idempotency_key: IdempotencyKeyHeader = None,
    ) -> SubmitResearchRunResponse:
        outcome = command.submit_research_run(
            _submission_key(idempotency_key),
            OnlyResearchSpecification.from_dict(request.specification),
        )
        response.headers["Location"] = f"/api/v2/research/runs/{outcome.run.run_id.value}"
        return SubmitResearchRunResponse.from_model(outcome)

    @router.get("/{run_id}", response_model=ResearchRunDto, responses=_ERROR_RESPONSES)
    def get_run(run_id: str) -> ResearchRunDto:
        return ResearchRunDto.from_model(query.get_run(_run_id(run_id)))

    @router.get("", response_model=ResearchRunPageDto, responses=_ERROR_RESPONSES)
    def list_runs(
        limit: int = Query(default=DEFAULT_RESEARCH_RUN_PAGE_SIZE), cursor: str | None = Query(default=None)
    ) -> ResearchRunPageDto:
        return ResearchRunPageDto.from_model(query.list_runs(limit=limit, cursor=cursor))

    @router.post("/{run_id}/cancellation", response_model=ResearchRunDto, responses=_ERROR_RESPONSES)
    def cancel_run(run_id: str) -> ResearchRunDto:
        return ResearchRunDto.from_model(command.request_research_run_cancellation(_run_id(run_id)))

    return router


__all__ = ["create_run_router"]
