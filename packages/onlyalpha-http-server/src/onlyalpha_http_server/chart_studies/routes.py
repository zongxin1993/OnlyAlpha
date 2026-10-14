"""Thin read-only Query transport; no Command, Receipt or scientific issuance."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from onlyalpha.application.chart_study_product_query import OnlyChartStudyProductQueryService, OnlyChartStudyQueryError
from onlyalpha.application.source_read_access import OnlySourceReadAccessError

from ..local_read_access import CHART_CAPABILITIES_PATH, CHART_EVALUATE_PATH, only_request_read_session
from .schema import (
    ChartStudyCapabilitiesDto,
    ChartStudyCapabilityDto,
    ChartStudyErrorEnvelopeDto,
    ChartStudyEvaluateDto,
    ChartStudyEvaluateRequestDto,
)

CHART_STUDY_ROUTE_TAG = "chart-studies"


def create_chart_study_router(service: OnlyChartStudyProductQueryService) -> APIRouter:
    router = APIRouter(
        tags=[CHART_STUDY_ROUTE_TAG],
        dependencies=[Depends(HTTPBearer(auto_error=False))],
        responses={status: {"model": ChartStudyErrorEnvelopeDto} for status in (400, 401, 403, 404, 409, 500, 503)},
    )

    def failure(error: Exception) -> JSONResponse:
        if isinstance(error, OnlyChartStudyQueryError):
            code, status = error.code, error.status
        elif isinstance(error, OnlySourceReadAccessError):
            code = error.code
            status = 401 if code == "LOCAL_READ_UNAUTHORIZED" else 403
        else:
            code, status = "CHART_STUDY_OUTPUT_INVALID", 500
        return JSONResponse(
            {"schema_version": 1, "error": {"phase": "QUERY", "code": code, "detail": code}},
            status_code=status,
            headers={"Cache-Control": "no-store"},
        )

    @router.get(CHART_CAPABILITIES_PATH, response_model=ChartStudyCapabilitiesDto)
    async def capabilities(request: Request) -> JSONResponse:
        session = only_request_read_session(request.scope)
        if session is None:
            return failure(OnlySourceReadAccessError("LOCAL_READ_UNAUTHORIZED"))
        try:

            def query() -> ChartStudyCapabilitiesDto:
                return ChartStudyCapabilitiesDto(
                    schema_version=1, capabilities=[ChartStudyCapabilityDto.from_model(service.capabilities(session))]
                )

            value = await run_in_threadpool(query)
            session.check_active()
            return JSONResponse(value.model_dump(mode="json"), headers={"Cache-Control": "no-store"})
        except Exception as error:
            return failure(error)

    @router.post(CHART_EVALUATE_PATH, response_model=ChartStudyEvaluateDto)
    async def evaluate(body: ChartStudyEvaluateRequestDto, request: Request) -> JSONResponse:
        session = only_request_read_session(request.scope)
        if session is None:
            return failure(OnlySourceReadAccessError("LOCAL_READ_UNAUTHORIZED"))
        try:
            model = body.to_model()

            def query() -> ChartStudyEvaluateDto:
                return ChartStudyEvaluateDto.from_model(service.evaluate(model, session))

            value = await run_in_threadpool(query)
            session.check_active()
            return JSONResponse(value.model_dump(mode="json"), headers={"Cache-Control": "no-store"})
        except ValidationError:
            return failure(OnlyChartStudyQueryError("CHART_STUDY_OUTPUT_INVALID", 500))
        except Exception as error:
            return failure(error)

    return router
