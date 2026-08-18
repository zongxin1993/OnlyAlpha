"""Dependency-injected portable and full Research FastAPI factories."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from onlyalpha.research.command.errors import OnlyResearchCommandError
from onlyalpha.research.command.query import OnlyResearchRunQueryService
from onlyalpha.research.command.service import OnlyResearchCommandService
from onlyalpha.research.query import OnlyResearchArtifactReader, OnlyResearchQueryError, OnlyResearchQueryService
from onlyalpha.research.run.errors import OnlyResearchRunError
from onlyalpha.research.specification.errors import OnlyResearchSpecificationError

from .research.errors import research_error_response
from .research.routes import create_artifact_router
from .research.run_errors import run_error_response
from .research.run_routes import create_run_router
from .research.run_schema import ResearchRunErrorDto, ResearchRunErrorEnvelopeDto
from .research.schema import RESEARCH_API_SCHEMA_VERSION, ResearchErrorDto

_RESEARCH_RUN_PATH = "/api/v2/research/runs"


def _artifact_validation_error_response() -> JSONResponse:
    body = ResearchErrorDto(code="INVALID_QUERY", detail="HTTP request validation failed")
    return JSONResponse(status_code=400, content=body.model_dump(mode="json"))


def _run_validation_error_response() -> JSONResponse:
    body = ResearchRunErrorEnvelopeDto(
        error=ResearchRunErrorDto(
            phase="COMMAND", code="RESEARCH_REQUEST_INVALID", detail="HTTP request validation failed"
        )
    )
    return JSONResponse(status_code=400, content=body.model_dump(mode="json"))


def _is_research_run_request(request: Request) -> bool:
    path = request.url.path
    return path == _RESEARCH_RUN_PATH or path.startswith(f"{_RESEARCH_RUN_PATH}/")


def create_artifact_query_app(reader: OnlyResearchArtifactReader) -> FastAPI:
    app = FastAPI(title="OnlyAlpha Research Artifact Query API", version=str(RESEARCH_API_SCHEMA_VERSION))
    service = OnlyResearchQueryService(reader)

    @app.exception_handler(OnlyResearchQueryError)
    async def query_error_handler(_request: Request, error: OnlyResearchQueryError) -> JSONResponse:
        status, body = research_error_response(error)
        return JSONResponse(status_code=status, content=body.model_dump(mode="json"))

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, _error: RequestValidationError) -> JSONResponse:
        return _artifact_validation_error_response()

    app.include_router(create_artifact_router(service))
    return app


def create_research_app(
    reader: OnlyResearchArtifactReader,
    command_service: OnlyResearchCommandService,
    run_query_service: OnlyResearchRunQueryService,
) -> FastAPI:
    app = create_artifact_query_app(reader)
    app.title = "OnlyAlpha Research API"

    async def command_error_handler(_request: Request, error: Exception) -> JSONResponse:
        status, body = run_error_response(error)
        return JSONResponse(status_code=status, content=body.model_dump(mode="json"))

    for error_type in (OnlyResearchCommandError, OnlyResearchRunError, OnlyResearchSpecificationError):
        app.add_exception_handler(error_type, command_error_handler)

    async def command_validation_error_handler(request: Request, _error: Exception) -> JSONResponse:
        if _is_research_run_request(request):
            return _run_validation_error_response()
        return _artifact_validation_error_response()

    app.add_exception_handler(RequestValidationError, command_validation_error_handler)
    app.include_router(create_run_router(command_service, run_query_service))
    return app


__all__ = ["create_artifact_query_app", "create_research_app"]
