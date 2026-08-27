"""Thin Research Run command and operational read HTTP adapter."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Response

from onlyalpha.application.product_boundary import (
    OnlyCancelResearchRun,
    OnlyCreateResearchRun,
    OnlyGetResearchRun,
    OnlyListResearchRuns,
    OnlyResearchProductBoundary,
)
from onlyalpha.research.command.errors import OnlyResearchCommandError, OnlyResearchCommandPhase
from onlyalpha.research.command.model import (
    OnlyResearchRunPage,
    OnlyResearchSubmissionKey,
    OnlyResearchSubmitOutcome,
)
from onlyalpha.research.command.query import DEFAULT_RESEARCH_RUN_PAGE_SIZE
from onlyalpha.research.run.model import OnlyResearchRun, OnlyResearchRunId
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
RUN_ROUTE_TAG = "research-runs"
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


def _expected_result[ResultT](value: object, result_type: type[ResultT]) -> ResultT:
    if not isinstance(value, result_type):
        raise TypeError(f"Product dispatcher returned {type(value).__name__}; expected {result_type.__name__}")
    return value


def create_run_router(product: OnlyResearchProductBoundary) -> APIRouter:
    router = APIRouter(prefix="/api/v2/research/runs", tags=[RUN_ROUTE_TAG])

    @router.post("", status_code=202, response_model=SubmitResearchRunResponse, responses=_ERROR_RESPONSES)
    def submit_run(
        request: SubmitResearchRunRequest,
        response: Response,
        idempotency_key: IdempotencyKeyHeader = None,
    ) -> SubmitResearchRunResponse:
        outcome = _expected_result(
            product.commands.dispatch(
                OnlyCreateResearchRun(
                    _submission_key(idempotency_key),
                    OnlyResearchSpecification.from_dict(request.specification),
                )
            ),
            OnlyResearchSubmitOutcome,
        )
        response.headers["Location"] = f"/api/v2/research/runs/{outcome.run.run_id.value}"
        return SubmitResearchRunResponse.from_model(outcome)

    @router.get("/{run_id}", response_model=ResearchRunDto, responses=_ERROR_RESPONSES)
    def get_run(run_id: str) -> ResearchRunDto:
        result = product.queries.dispatch(OnlyGetResearchRun(_run_id(run_id)))
        return ResearchRunDto.from_model(_expected_result(result, OnlyResearchRun))

    @router.get("", response_model=ResearchRunPageDto, responses=_ERROR_RESPONSES)
    def list_runs(
        limit: int = Query(default=DEFAULT_RESEARCH_RUN_PAGE_SIZE), cursor: str | None = Query(default=None)
    ) -> ResearchRunPageDto:
        result = product.queries.dispatch(OnlyListResearchRuns(limit=limit, cursor=cursor))
        return ResearchRunPageDto.from_model(_expected_result(result, OnlyResearchRunPage))

    @router.post("/{run_id}/cancellation", response_model=ResearchRunDto, responses=_ERROR_RESPONSES)
    def cancel_run(run_id: str, idempotency_key: IdempotencyKeyHeader = None) -> ResearchRunDto:
        result = product.commands.dispatch(
            OnlyCancelResearchRun(
                _run_id(run_id),
                None if idempotency_key is None else _submission_key(idempotency_key),
            )
        )
        return ResearchRunDto.from_model(_expected_result(result, OnlyResearchRun))

    return router


__all__ = ["RUN_ROUTE_TAG", "create_run_router"]
