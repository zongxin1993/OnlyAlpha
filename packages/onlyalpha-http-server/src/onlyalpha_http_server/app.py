"""Dependency-injected Product Research FastAPI factory."""

from __future__ import annotations

from typing import Any, cast

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.params import Depends as DependsParam
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from onlyalpha.application.product_boundary import OnlyResearchProductBoundary
from onlyalpha.application.qualification_product import (
    OnlyQualificationProductService,
    OnlyQualificationQueryService,
)
from onlyalpha.application.strategy_product import (
    OnlyStrategyFreezeProductService,
    OnlyStrategyPromotionProductService,
    OnlyStrategyQueryService,
)
from onlyalpha.backtest import OnlyBacktestCommandService, OnlyBacktestQueryService
from onlyalpha.backtest.errors import (
    OnlyBacktestError,
    OnlyBacktestIntegrityError,
    OnlyBacktestNotFoundError,
    OnlyBacktestStateConflictError,
    OnlyBacktestStoreUnavailableError,
)
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.kernel import OnlyKernelAuthorityError, OnlyKernelMutationRejected
from onlyalpha.research.command.errors import OnlyResearchCommandError
from onlyalpha.research.definition.errors import OnlyResearchDefinitionError
from onlyalpha.research.definition.ports import OnlyResearchUniverseCatalog
from onlyalpha.research.definition.resolver import OnlyResearchDefinitionResolver
from onlyalpha.research.operations.readiness import (
    OnlyResearchReadiness,
    OnlyResearchReadinessStatus,
)
from onlyalpha.research.query import OnlyResearchArtifactReader, OnlyResearchQueryError, OnlyResearchQueryService
from onlyalpha.research.run.errors import OnlyResearchRunError
from onlyalpha.research.specification.errors import OnlyResearchSpecificationError
from onlyalpha.strategy.errors import OnlyStrategyError

from .backtest.routes import BACKTEST_ROUTE_TAG, create_backtest_router
from .backtest.schema import ProductErrorDto, ProductErrorEnvelopeDto
from .health import OnlyKernelResearchReadinessProjection, OnlyProductExecutionCapacityProbe, create_health_router
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
from .strategy.routes import STRATEGY_ROUTE_TAG, create_strategy_router


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
        tag
        for tag in tags
        if tag
        in {
            RUN_ROUTE_TAG,
            ARTIFACT_ROUTE_TAG,
            DEFINITION_ROUTE_TAG,
            DISCOVERY_ROUTE_TAG,
            STRATEGY_ROUTE_TAG,
            BACKTEST_ROUTE_TAG,
        }
    )
    return known[0] if len(known) == 1 else None


class _ResearchServiceNotReady(RuntimeError):
    def __init__(self, readiness: OnlyResearchReadiness) -> None:
        self.readiness = readiness
        super().__init__(readiness.reason or "RESEARCH_SERVICE_NOT_READY")


def create_research_app(
    reader: OnlyResearchArtifactReader,
    product_boundary: OnlyResearchProductBoundary,
    calculation_registry: OnlyCalculationRegistry,
    definition_resolver: OnlyResearchDefinitionResolver,
    readiness_probe: OnlyKernelResearchReadinessProjection,
    strategy_freeze: OnlyStrategyFreezeProductService | None = None,
    strategy_promotion: OnlyStrategyPromotionProductService | None = None,
    strategy_query: OnlyStrategyQueryService | None = None,
    qualification: OnlyQualificationProductService | None = None,
    qualification_query: OnlyQualificationQueryService | None = None,
    backtest_commands: OnlyBacktestCommandService | None = None,
    backtest_queries: OnlyBacktestQueryService | None = None,
    execution_capacity: OnlyProductExecutionCapacityProbe | None = None,
) -> FastAPI:
    universe_authority = definition_resolver.universe_resolver
    if universe_authority is not None and not isinstance(universe_authority, OnlyResearchUniverseCatalog):
        raise TypeError("Research API registered Universe authority must support both resolution and discovery")
    app = FastAPI(title="OnlyAlpha Research API", version=str(RESEARCH_API_SCHEMA_VERSION))
    artifact_service = OnlyResearchQueryService(reader)

    def require_research_ready() -> None:
        inspected = readiness_probe.inspect()
        if inspected.status is not OnlyResearchReadinessStatus.READY:
            raise _ResearchServiceNotReady(inspected)

    readiness_dependencies: list[DependsParam] = [Depends(require_research_ready)]

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

    async def kernel_mutation_error_handler(_request: Request, error: Exception) -> JSONResponse:
        code = (
            "PRODUCT_KERNEL_MUTATION_UNAVAILABLE"
            if isinstance(error, OnlyKernelMutationRejected)
            else "PRODUCT_KERNEL_AUTHORITY_UNAVAILABLE"
        )
        body = ResearchRunErrorEnvelopeDto(
            error=ResearchRunErrorDto(
                phase="OPERATIONAL",
                code=code,
                detail="Product Kernel mutation is unavailable",
            )
        )
        return JSONResponse(status_code=503, content=body.model_dump(mode="json"))

    for kernel_error_type in (OnlyKernelAuthorityError, OnlyKernelMutationRejected):
        app.add_exception_handler(kernel_error_type, kernel_mutation_error_handler)

    for command_error_type in (
        OnlyResearchCommandError,
        OnlyResearchRunError,
        OnlyResearchSpecificationError,
    ):
        app.add_exception_handler(command_error_type, command_error_handler)

    async def definition_domain_error_handler(_request: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, OnlyResearchDefinitionError)
        status, body = definition_error_response(error)
        return JSONResponse(status_code=status, content=body.model_dump(mode="json"))

    app.add_exception_handler(OnlyResearchDefinitionError, definition_domain_error_handler)

    async def product_error_handler(_request: Request, error: Exception) -> JSONResponse:
        if isinstance(error, OnlyBacktestError):
            phase = error.phase.value
            code = error.code
            detail = error.detail
            if isinstance(error, OnlyBacktestNotFoundError) or code.endswith("_NOT_FOUND"):
                status = 404
            elif isinstance(error, OnlyBacktestStoreUnavailableError) or code.endswith("_UNAVAILABLE"):
                status = 503
                detail = "Required Product authority is unavailable"
            elif isinstance(error, OnlyBacktestIntegrityError) or "CORRUPT" in code:
                status = 500
                detail = "Verified Product authority is corrupt"
            elif isinstance(error, OnlyBacktestStateConflictError) or "CONFLICT" in code or "NOT_ADMITTED" in code:
                status = 409
            else:
                status = 400
        else:
            assert isinstance(error, OnlyStrategyError)
            phase = "COMMAND"
            code = error.code
            detail = error.detail or code
            if code.endswith("_NOT_FOUND"):
                status = 404
            elif "UNAVAILABLE" in code:
                status = 503
                detail = "Required Product authority is unavailable"
            elif "CORRUPT" in code:
                status = 500
                detail = "Verified Product authority is corrupt"
            elif "CONFLICT" in code or "INVALID" in code:
                status = 409
            else:
                status = 400
        body = ProductErrorEnvelopeDto(error=ProductErrorDto(phase=phase, code=code, detail=detail))
        return JSONResponse(status_code=status, content=body.model_dump(mode="json"))

    app.add_exception_handler(OnlyBacktestError, product_error_handler)
    app.add_exception_handler(OnlyStrategyError, product_error_handler)

    async def product_value_error_handler(request: Request, _error: Exception) -> JSONResponse:
        if _request_route_tag(request) not in {STRATEGY_ROUTE_TAG, BACKTEST_ROUTE_TAG}:
            return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})
        body = ProductErrorEnvelopeDto(
            error=ProductErrorDto(
                phase="COMMAND",
                code="PRODUCT_REQUEST_INVALID",
                detail="HTTP request validation failed",
            )
        )
        return JSONResponse(status_code=400, content=body.model_dump(mode="json"))

    app.add_exception_handler(ValueError, product_value_error_handler)

    async def request_validation_error_handler(request: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, RequestValidationError)
        family = _request_route_tag(request)
        if family == RUN_ROUTE_TAG:
            return _run_validation_error_response()
        if family == ARTIFACT_ROUTE_TAG:
            return _artifact_validation_error_response()
        if family == DEFINITION_ROUTE_TAG:
            return _definition_validation_error_response(error)
        if family in {STRATEGY_ROUTE_TAG, BACKTEST_ROUTE_TAG}:
            body = ProductErrorEnvelopeDto(
                error=ProductErrorDto(
                    phase="COMMAND",
                    code="PRODUCT_REQUEST_INVALID",
                    detail="HTTP request validation failed",
                )
            )
            return JSONResponse(status_code=400, content=body.model_dump(mode="json"))
        return JSONResponse(status_code=400, content={"detail": "HTTP request validation failed"})

    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    app.include_router(create_artifact_router(artifact_service), dependencies=readiness_dependencies)
    app.include_router(create_run_router(product_boundary), dependencies=readiness_dependencies)
    app.include_router(
        create_discovery_router(ResearchDiscoveryService(calculation_registry, universe_authority)),
        dependencies=readiness_dependencies,
    )
    app.include_router(
        create_definition_router(ResearchDefinitionApiService(definition_resolver)),
        dependencies=readiness_dependencies,
    )
    app.include_router(create_health_router(readiness_probe, execution_capacity))
    if any(
        item is not None
        for item in (strategy_freeze, strategy_promotion, strategy_query, qualification, qualification_query)
    ):
        if any(
            item is None
            for item in (strategy_freeze, strategy_promotion, strategy_query, qualification, qualification_query)
        ):
            raise TypeError("Strategy Product routes require all Strategy services")
        assert strategy_freeze is not None
        assert strategy_promotion is not None
        assert strategy_query is not None
        assert qualification is not None
        assert qualification_query is not None
        app.include_router(
            create_strategy_router(
                strategy_freeze,
                strategy_promotion,
                strategy_query,
                qualification,
                qualification_query,
            ),
            dependencies=readiness_dependencies,
        )
    if backtest_commands is not None or backtest_queries is not None:
        if backtest_commands is None or backtest_queries is None:
            raise TypeError("Backtest Product routes require command and query services")
        app.include_router(
            create_backtest_router(backtest_commands, backtest_queries),
            dependencies=readiness_dependencies,
        )
    _install_exact_product_openapi(app)
    return app


def _install_exact_product_openapi(app: FastAPI) -> None:
    """Remove FastAPI's synthetic 422 from routes whose runtime maps validation to 400."""

    generated_openapi = app.openapi

    def exact_product_openapi() -> dict[str, Any]:
        document = generated_openapi()
        paths = document.get("paths", {})
        if isinstance(paths, dict):
            for path_item in paths.values():
                if not isinstance(path_item, dict):
                    continue
                for operation in path_item.values():
                    if not isinstance(operation, dict):
                        continue
                    tags = operation.get("tags", [])
                    responses = operation.get("responses", {})
                    if (
                        isinstance(tags, list)
                        and ({STRATEGY_ROUTE_TAG, BACKTEST_ROUTE_TAG} & set(tags))
                        and isinstance(responses, dict)
                    ):
                        responses.pop("422", None)
        return document

    cast(Any, app).openapi = exact_product_openapi


def create_product_app(
    reader: OnlyResearchArtifactReader,
    product_boundary: OnlyResearchProductBoundary,
    calculation_registry: OnlyCalculationRegistry,
    definition_resolver: OnlyResearchDefinitionResolver,
    readiness_probe: OnlyKernelResearchReadinessProjection,
    strategy_freeze: OnlyStrategyFreezeProductService,
    strategy_promotion: OnlyStrategyPromotionProductService,
    strategy_query: OnlyStrategyQueryService,
    qualification: OnlyQualificationProductService,
    qualification_query: OnlyQualificationQueryService,
    backtest_commands: OnlyBacktestCommandService,
    backtest_queries: OnlyBacktestQueryService,
    execution_capacity: OnlyProductExecutionCapacityProbe | None = None,
) -> FastAPI:
    app = create_research_app(
        reader,
        product_boundary,
        calculation_registry,
        definition_resolver,
        readiness_probe,
        strategy_freeze,
        strategy_promotion,
        strategy_query,
        qualification,
        qualification_query,
        backtest_commands,
        backtest_queries,
        execution_capacity,
    )
    app.title = "OnlyAlpha Product API"
    return app


__all__ = ["create_product_app", "create_research_app"]
