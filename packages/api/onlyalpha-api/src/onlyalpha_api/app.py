"""Dependency-injected FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from onlyalpha.research.query import (
    OnlyResearchArtifactReader,
    OnlyResearchQueryError,
    OnlyResearchQueryService,
)

from .research.errors import research_error_response
from .research.routes import create_research_router
from .research.schema import RESEARCH_API_SCHEMA_VERSION, ResearchErrorDto


def create_app(reader: OnlyResearchArtifactReader) -> FastAPI:
    app = FastAPI(title="OnlyAlpha Research Read API", version=str(RESEARCH_API_SCHEMA_VERSION))
    service = OnlyResearchQueryService(reader)

    @app.exception_handler(OnlyResearchQueryError)
    async def query_error_handler(_request: Request, error: OnlyResearchQueryError) -> JSONResponse:
        status, body = research_error_response(error)
        return JSONResponse(status_code=status, content=body.model_dump(mode="json"))

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, _error: RequestValidationError) -> JSONResponse:
        body = ResearchErrorDto(code="INVALID_QUERY", detail="HTTP request validation failed")
        return JSONResponse(status_code=400, content=body.model_dump(mode="json"))

    app.include_router(create_research_router(service))
    return app
