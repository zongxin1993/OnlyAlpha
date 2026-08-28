"""Test-only HTTP composition for portable Research Artifact fixtures."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from onlyalpha_api.research.errors import research_error_response
from onlyalpha_api.research.routes import create_artifact_router
from onlyalpha_api.research.schema import RESEARCH_API_SCHEMA_VERSION, ResearchErrorDto

from onlyalpha.research.query import OnlyResearchArtifactReader, OnlyResearchQueryError, OnlyResearchQueryService


def create_test_artifact_query_app(reader: OnlyResearchArtifactReader) -> FastAPI:
    app = FastAPI(title="OnlyAlpha Test Artifact Query API", version=str(RESEARCH_API_SCHEMA_VERSION))

    @app.exception_handler(OnlyResearchQueryError)
    async def query_error_handler(_request: Request, error: OnlyResearchQueryError) -> JSONResponse:
        status, body = research_error_response(error)
        return JSONResponse(status_code=status, content=body.model_dump(mode="json"))

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, _error: RequestValidationError) -> JSONResponse:
        body = ResearchErrorDto(code="INVALID_QUERY", detail="HTTP request validation failed")
        return JSONResponse(status_code=400, content=body.model_dump(mode="json"))

    app.include_router(create_artifact_router(OnlyResearchQueryService(reader)))
    return app


__all__ = ["create_test_artifact_query_app"]
