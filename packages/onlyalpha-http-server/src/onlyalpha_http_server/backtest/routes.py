"""Thin Backtest Product command/query HTTP adapter."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, Response

from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.backtest import (
    OnlyBacktestCommandService,
    OnlyBacktestProfileReference,
    OnlyBacktestQueryService,
    OnlyBacktestRun,
    OnlyBacktestRunId,
    OnlyBacktestSpecification,
)

from .schema import (
    BacktestCancellationResponse,
    BacktestEvidenceDto,
    BacktestFailureDto,
    BacktestRunCreateRequest,
    BacktestRunCreateResponse,
    BacktestRunDto,
)

BACKTEST_ROUTE_TAG = "backtest"
IdempotencyKeyHeader = Annotated[str, Header(alias="Idempotency-Key")]
_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {status: {} for status in (400, 404, 409, 500, 503)}


def create_backtest_router(commands: OnlyBacktestCommandService, queries: OnlyBacktestQueryService) -> APIRouter:
    router = APIRouter(prefix="/api/v2/backtest", tags=[BACKTEST_ROUTE_TAG])

    @router.post("/runs", status_code=202, response_model=BacktestRunCreateResponse, responses=_ERROR_RESPONSES)
    def create_run(
        request: BacktestRunCreateRequest,
        response: Response,
        idempotency_key: IdempotencyKeyHeader,
    ) -> BacktestRunCreateResponse:
        outcome = commands.submit(_command_id(idempotency_key), _specification(request))
        response.headers["Location"] = f"/api/v2/backtest/runs/{outcome.run.run_id.value}"
        return BacktestRunCreateResponse(
            backtest_run_id=outcome.run.run_id.value,
            state=outcome.run.state.value,
            disposition=outcome.disposition.value,
        )

    @router.get("/runs/{run_id}", response_model=BacktestRunDto, responses=_ERROR_RESPONSES)
    def get_run(run_id: str) -> BacktestRunDto:
        return _run_dto(queries.get(_run_id(run_id)))

    @router.post(
        "/runs/{run_id}/cancellation",
        status_code=202,
        response_model=BacktestCancellationResponse,
        responses=_ERROR_RESPONSES,
    )
    def cancel_run(run_id: str, idempotency_key: IdempotencyKeyHeader) -> BacktestCancellationResponse:
        run = commands.cancel(_run_id(run_id), _command_id(idempotency_key))
        return BacktestCancellationResponse(run_id=run.run_id.value, state=run.state.value, revision=run.revision)

    @router.get("/runs/{run_id}/evidence", response_model=BacktestEvidenceDto, responses=_ERROR_RESPONSES)
    def get_evidence(run_id: str) -> BacktestEvidenceDto:
        return BacktestEvidenceDto(manifest=queries.evidence(_run_id(run_id)).to_dict())

    @router.get("/runs/{run_id}/evidence/artifacts/{artifact_name:path}", responses=_ERROR_RESPONSES)
    def get_artifact(run_id: str, artifact_name: str) -> Response:
        artifact = queries.artifact(_run_id(run_id), artifact_name)
        return Response(content=artifact.content, media_type=artifact.media_type)

    return router


def _command_id(value: str) -> OnlyProductCommandId:
    return OnlyProductCommandId(value)


def _run_id(value: str) -> OnlyBacktestRunId:
    return OnlyBacktestRunId(value)


def _specification(request: BacktestRunCreateRequest) -> OnlyBacktestSpecification:
    return OnlyBacktestSpecification(
        strategy_fingerprint=request.strategy_fingerprint,
        dataset_binding_fingerprint=request.dataset_binding_fingerprint,
        market_product_configuration_fingerprint=request.market_product_configuration_fingerprint,
        portfolio_profile=OnlyBacktestProfileReference(**request.portfolio_profile.model_dump()),
        risk_profile=OnlyBacktestProfileReference(**request.risk_profile.model_dump()),
        execution_profile=OnlyBacktestProfileReference(**request.execution_profile.model_dump()),
        base_currency=request.initial_account.base_currency,
        initial_capital=request.initial_account.capital,
        ordered_fact_policy=request.runtime_options.ordered_fact_policy,
        schema_version=request.schema_version,
    )


def _run_dto(run: OnlyBacktestRun) -> BacktestRunDto:
    failure = None
    if run.failure is not None:
        failure = BacktestFailureDto(
            phase=run.failure.phase.value,
            code=run.failure.code,
            detail=run.failure.detail,
        )
    return BacktestRunDto(
        run_id=run.run_id.value,
        state=run.state.value,
        revision=run.revision,
        specification_fingerprint=run.specification_fingerprint,
        admission_resolution_fingerprint=run.admission_resolution_fingerprint,
        queued_at=run.queued_at.isoformat(),
        started_at=None if run.started_at is None else run.started_at.isoformat(),
        cancel_requested_at=None if run.cancel_requested_at is None else run.cancel_requested_at.isoformat(),
        finished_at=None if run.finished_at is None else run.finished_at.isoformat(),
        result_fingerprint=run.result_fingerprint,
        evidence_fingerprint=run.evidence_fingerprint,
        determinism_fingerprint=run.determinism_fingerprint,
        failure=failure,
    )


__all__ = ["BACKTEST_ROUTE_TAG", "create_backtest_router"]
