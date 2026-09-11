"""Thin Research Run command and operational read HTTP adapter."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, Path, Query, Response

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
    ResearchRunExecutionEvidenceDto,
    ResearchRunPageDto,
    SubmitResearchRunRequest,
    SubmitResearchRunResponse,
)

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ResearchRunErrorEnvelopeDto} for status in (400, 404, 409, 500, 503)
}
_SUBMIT_RESPONSES: dict[int | str, dict[str, Any]] = {
    **_ERROR_RESPONSES,
    202: {
        "headers": {
            "Idempotency-Key": {
                "description": "Exact admitted Product Command identity",
                "schema": {"type": "string"},
            }
        }
    },
}
RUN_ROUTE_TAG = "research-runs"
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]
RequiredIdempotencyKeyHeader = Annotated[str, Header(alias="Idempotency-Key")]
ResearchRunPath = Annotated[
    str,
    Path(
        json_schema_extra={
            "x-onlyalpha-reference-kind": "RESEARCH_RUN",
            "x-onlyalpha-reference-schema-version": 1,
            "x-onlyalpha-reference-locator-kind": "UUID4",
        }
    ),
]


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

    def submit(
        request: SubmitResearchRunRequest,
        response: Response,
        idempotency_key: str,
    ) -> SubmitResearchRunResponse:
        submission_key = _submission_key(idempotency_key)
        outcome = _expected_result(
            product.commands.dispatch(
                OnlyCreateResearchRun(
                    submission_key,
                    OnlyResearchSpecification.from_dict(request.specification),
                    None if request.authoring_provenance is None else request.authoring_provenance.to_model(),
                )
            ),
            OnlyResearchSubmitOutcome,
        )
        response.headers["Location"] = f"/api/v2/research/runs/{outcome.run.run_id.value}"
        response.headers["Idempotency-Key"] = submission_key.value
        return SubmitResearchRunResponse.from_model(outcome)

    @router.post(
        "",
        status_code=202,
        response_model=SubmitResearchRunResponse,
        responses=_SUBMIT_RESPONSES,
    )
    def submit_run(
        request: SubmitResearchRunRequest,
        response: Response,
        idempotency_key: IdempotencyKeyHeader = None,
    ) -> SubmitResearchRunResponse:
        return submit(request, response, _submission_key(idempotency_key).value)

    @router.post(
        "/commands",
        operation_id="submit_research_run_command_v2",
        status_code=202,
        response_model=SubmitResearchRunResponse,
        responses=_SUBMIT_RESPONSES,
        openapi_extra={
            "x-onlyalpha-agent-operation": {
                "schema_version": 1,
                "tool_class": "RESEARCH_RUN_SUBMIT",
                "recovery_class": "IDEMPOTENT_COMMAND",
                "requires_product_command_id": True,
                "product_command_id_transport": {"in": "header", "name": "Idempotency-Key"},
                "identity_requirements": [],
                "owning_authority_references": [
                    {
                        "reference_kind": "RESEARCH_RUN",
                        "reference_schema_version": 1,
                        "locator_kind": "UUID4",
                        "response_field": "run.run_id",
                    }
                ],
                "response_effect_semantics": {
                    "202": "COMMITTED_RESPONSE",
                    "400": "DEFINITIVE_PRE_ADMISSION_REJECTION",
                    "404": "DEFINITIVE_PRE_ADMISSION_REJECTION",
                    "409": "DEFINITIVE_PRE_ADMISSION_REJECTION",
                    "422": "DEFINITIVE_PRE_ADMISSION_REJECTION",
                    "500": "EFFECT_UNKNOWN",
                    "502": "EFFECT_UNKNOWN",
                    "503": "EFFECT_UNKNOWN",
                    "504": "EFFECT_UNKNOWN",
                },
            }
        },
    )
    def submit_run_command(
        request: SubmitResearchRunRequest,
        response: Response,
        idempotency_key: RequiredIdempotencyKeyHeader,
    ) -> SubmitResearchRunResponse:
        return submit(request, response, idempotency_key)

    @router.get(
        "/{run_id}",
        response_model=ResearchRunDto,
        responses=_ERROR_RESPONSES,
        openapi_extra={
            "x-onlyalpha-agent-operation": {
                "schema_version": 1,
                "tool_class": "RESEARCH_RUN_QUERY",
                "recovery_class": "MUTABLE_OBSERVATION_QUERY",
                "requires_product_command_id": False,
                "product_command_id_transport": None,
                "identity_requirements": ["run_id"],
                "owning_authority_references": [
                    {
                        "reference_kind": "RESEARCH_RUN",
                        "reference_schema_version": 1,
                        "locator_kind": "UUID4",
                        "response_field": "run_id",
                    }
                ],
            }
        },
    )
    def get_run(run_id: ResearchRunPath) -> ResearchRunDto:
        result = product.queries.dispatch(OnlyGetResearchRun(_run_id(run_id)))
        return ResearchRunDto.from_model(_expected_result(result, OnlyResearchRun))

    @router.get(
        "/{run_id}/execution-evidence",
        response_model=ResearchRunExecutionEvidenceDto,
        responses=_ERROR_RESPONSES,
    )
    def get_run_execution_evidence(run_id: str) -> ResearchRunExecutionEvidenceDto:
        result = product.queries.dispatch(OnlyGetResearchRun(_run_id(run_id)))
        return ResearchRunExecutionEvidenceDto.from_model(_expected_result(result, OnlyResearchRun))

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
