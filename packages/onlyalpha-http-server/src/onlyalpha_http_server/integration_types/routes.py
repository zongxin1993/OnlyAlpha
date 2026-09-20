"""Read-only Integration Type Product routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from onlyalpha.application.integration_type_catalog import (
    OnlyIntegrationTypeCatalog,
    OnlyIntegrationTypeCatalogError,
)
from onlyalpha.plugin.integration import OnlyIntegrationCategory

from .schema import (
    IntegrationTypeDto,
    IntegrationTypeErrorDto,
    IntegrationTypeErrorEnvelopeDto,
    IntegrationTypeListDto,
)

INTEGRATION_TYPE_ROUTE_TAG = "integration-types"
_LIST_ERRORS: dict[int | str, dict[str, Any]] = {
    400: {"model": IntegrationTypeErrorEnvelopeDto, "description": "Invalid Integration Type query"},
}
_READ_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": IntegrationTypeErrorEnvelopeDto, "description": "Integration Type not found"},
}


def integration_type_error_response(status: int, code: str, detail: str) -> JSONResponse:
    body = IntegrationTypeErrorEnvelopeDto(error=IntegrationTypeErrorDto(code=code, detail=detail))
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


def create_integration_type_router(catalog: OnlyIntegrationTypeCatalog) -> APIRouter:
    router = APIRouter(prefix="/api/v2/integration-types", tags=[INTEGRATION_TYPE_ROUTE_TAG])

    @router.get("", response_model=IntegrationTypeListDto, responses=_LIST_ERRORS)
    def list_integration_types(category: str | None = None) -> IntegrationTypeListDto | JSONResponse:
        selected = None
        if category is not None:
            try:
                selected = OnlyIntegrationCategory(category)
            except ValueError:
                return integration_type_error_response(
                    400, "INTEGRATION_TYPE_CONTRACT_INVALID", "Unknown Integration Type category"
                )
        return IntegrationTypeListDto(
            items=tuple(IntegrationTypeDto.from_model(item) for item in catalog.list(selected))
        )

    @router.get("/{type_id}", response_model=IntegrationTypeDto, responses=_READ_ERRORS)
    def get_integration_type(type_id: str) -> IntegrationTypeDto | JSONResponse:
        try:
            return IntegrationTypeDto.from_model(catalog.require(type_id))
        except OnlyIntegrationTypeCatalogError as error:
            return integration_type_error_response(404, error.code, error.detail)

    return router


__all__ = [
    "INTEGRATION_TYPE_ROUTE_TAG",
    "create_integration_type_router",
    "integration_type_error_response",
]
