"""Dependency-injected portable and full Research FastAPI factories."""

from __future__ import annotations

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.params import Depends as DependsParam
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.research.command.errors import OnlyResearchCommandError
from onlyalpha.research.command.query import OnlyResearchRunQueryService
from onlyalpha.research.command.service import OnlyResearchCommandService
from onlyalpha.research.definition.errors import OnlyResearchDefinitionError
from onlyalpha.research.definition.ports import OnlyResearchUniverseCatalog
from onlyalpha.research.definition.resolver import OnlyResearchDefinitionResolver
from onlyalpha.research.operations.readiness import (
    OnlyResearchReadiness,
    OnlyResearchReadinessStatus,
    OnlyResearchServiceReadinessProbe,
)
from onlyalpha.research.query import OnlyResearchArtifactReader, OnlyResearchQueryError, OnlyResearchQueryService
from onlyalpha.research.run.errors import OnlyResearchRunError
from onlyalpha.research.specification.errors import OnlyResearchSpecificationError

from .health import create_health_router
from .research.definition_errors import definition_error_response
from .research.definition_routes import (
    DEFINITION_ROUTE_TAG,
    DISCOVERY_ROUTE_TAG,
    create_definition_router,
    create_discovery_router,
)
from .research.definition_schema import ResearchDefinitionErrorDto, ResearchDefinitionErrorEnvelopeDto
from .research.definition_service import ResearchDefinitionApiService
from .research.discovery import ResearchDiscoveryService
from .research.errors import research_error_response
from .research.routes import ARTIFACT_ROUTE_TAG, create_artifact_router
from .research.run_errors import run_error_response
from .research.run_routes import RUN_ROUTE_TAG, create_run_router
from .research.run_schema import ResearchRunErrorDto, ResearchRunErrorEnvelopeDto
from .research.schema import RESEARCH_API_SCHEMA_VERSION, ResearchErrorDto


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


def _definition_validation_error_response(error: RequestValidationError) -> JSONResponse:
    location = error.errors()[0].get("loc", ()) if error.errors() else ()
    parts = tuple(item for item in location if item != "body")
    path = "$"
    for item in parts:
        path += f"[{item}]" if isinstance(item, int) else f".{item}"
    if path.startswith("$."):
        path = path[2:]
    body = ResearchDefinitionErrorEnvelopeDto(
        error=ResearchDefinitionErrorDto(
            phase="SCHEMA",
            code="RESEARCH_DEFINITION_REQUEST_INVALID",
            path=path,
            detail="HTTP request validation failed",
        )
    )
    return JSONResponse(status_code=400, content=body.model_dump(mode="json"))


def _request_route_tag(request: Request) -> str | None:
    route = request.scope.get("route")
    if not isinstance(route, APIRoute):
        return None
    tags = tuple(route.tags)
    known = tuple(
        tag for tag in tags if tag in {RUN_ROUTE_TAG, ARTIFACT_ROUTE_TAG, DEFINITION_ROUTE_TAG, DISCOVERY_ROUTE_TAG}
    )
    return known[0] if len(known) == 1 else None


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


class _ResearchServiceNotReady(RuntimeError):
    def __init__(self, readiness: OnlyResearchReadiness) -> None:
        self.readiness = readiness
        super().__init__(readiness.reason or "RESEARCH_SERVICE_NOT_READY")


def create_research_app(
    reader: OnlyResearchArtifactReader,
    command_service: OnlyResearchCommandService,
    run_query_service: OnlyResearchRunQueryService,
    calculation_registry: OnlyCalculationRegistry,
    definition_resolver: OnlyResearchDefinitionResolver,
    readiness_probe: OnlyResearchServiceReadinessProbe | None = None,
) -> FastAPI:
    universe_authority = definition_resolver.universe_resolver
    if universe_authority is not None and not isinstance(universe_authority, OnlyResearchUniverseCatalog):
        raise TypeError("Research API registered Universe authority must support both resolution and discovery")
    app = FastAPI(title="OnlyAlpha Research API", version=str(RESEARCH_API_SCHEMA_VERSION))
    artifact_service = OnlyResearchQueryService(reader)
    readiness_dependencies: list[DependsParam] = []
    if readiness_probe is not None:

        def require_research_ready() -> None:
            inspected = readiness_probe.inspect()
            if inspected.status is not OnlyResearchReadinessStatus.READY:
                raise _ResearchServiceNotReady(inspected)

        readiness_dependencies.append(Depends(require_research_ready))

    @app.exception_handler(_ResearchServiceNotReady)
    async def not_ready_handler(_request: Request, error: _ResearchServiceNotReady) -> JSONResponse:
        inspected = error.readiness
        return JSONResponse(
            status_code=503,
            content={
                "status": inspected.status.value,
                "checks": {item.name: item.status for item in inspected.checks},
                "reason": inspected.reason,
            },
        )

    @app.exception_handler(OnlyResearchQueryError)
    async def query_error_handler(_request: Request, error: OnlyResearchQueryError) -> JSONResponse:
        status, body = research_error_response(error)
        return JSONResponse(status_code=status, content=body.model_dump(mode="json"))

    async def command_error_handler(_request: Request, error: Exception) -> JSONResponse:
        status, body = run_error_response(error)
        return JSONResponse(status_code=status, content=body.model_dump(mode="json"))

    for error_type in (OnlyResearchCommandError, OnlyResearchRunError, OnlyResearchSpecificationError):
        app.add_exception_handler(error_type, command_error_handler)

    async def definition_domain_error_handler(_request: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, OnlyResearchDefinitionError)
        status, body = definition_error_response(error)
        return JSONResponse(status_code=status, content=body.model_dump(mode="json"))

    app.add_exception_handler(OnlyResearchDefinitionError, definition_domain_error_handler)

    async def request_validation_error_handler(request: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, RequestValidationError)
        family = _request_route_tag(request)
        if family == RUN_ROUTE_TAG:
            return _run_validation_error_response()
        if family == ARTIFACT_ROUTE_TAG:
            return _artifact_validation_error_response()
        if family == DEFINITION_ROUTE_TAG:
            return _definition_validation_error_response(error)
        return JSONResponse(status_code=400, content={"detail": "HTTP request validation failed"})

    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    app.include_router(create_artifact_router(artifact_service), dependencies=readiness_dependencies)
    app.include_router(create_run_router(command_service, run_query_service), dependencies=readiness_dependencies)
    app.include_router(
        create_discovery_router(ResearchDiscoveryService(calculation_registry, universe_authority)),
        dependencies=readiness_dependencies,
    )
    app.include_router(
        create_definition_router(ResearchDefinitionApiService(definition_resolver)),
        dependencies=readiness_dependencies,
    )
    app.include_router(create_health_router(readiness_probe))
    return app


__all__ = ["create_artifact_query_app", "create_research_app"]
