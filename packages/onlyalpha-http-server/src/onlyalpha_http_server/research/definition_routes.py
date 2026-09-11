"""Thin Discovery and Research Definition HTTP routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from .definition_schema import (
    ResearchCalculationCatalogDto,
    ResearchCalculationCatalogItemDto,
    ResearchDatasetFieldCatalogDto,
    ResearchDatasetFieldDto,
    ResearchDefinitionErrorEnvelopeDto,
    ResearchDefinitionRequestDto,
    ResearchDefinitionResolutionDto,
    ResearchStatisticsCapabilityCatalogDto,
    ResearchStatisticsCapabilityDto,
    ResearchUniverseCatalogDto,
)
from .definition_service import ResearchDefinitionApiService
from .discovery import ResearchDiscoveryService

DISCOVERY_ROUTE_TAG = "research-discovery"
DEFINITION_ROUTE_TAG = "research-definitions"
_DEFINITION_ERRORS: dict[int | str, dict[str, Any]] = {
    400: {"model": ResearchDefinitionErrorEnvelopeDto, "description": "Invalid Research Definition"}
}


def create_discovery_router(service: ResearchDiscoveryService) -> APIRouter:
    router = APIRouter(prefix="/api/v2/research/catalog", tags=[DISCOVERY_ROUTE_TAG])

    @router.get("/calculations", response_model=ResearchCalculationCatalogDto)
    def calculations() -> ResearchCalculationCatalogDto:
        return ResearchCalculationCatalogDto(
            calculations=tuple(ResearchCalculationCatalogItemDto.from_model(item) for item in service.calculations())
        )

    @router.get("/universes", response_model=ResearchUniverseCatalogDto)
    def universes() -> ResearchUniverseCatalogDto:
        return ResearchUniverseCatalogDto.from_model(service.universes())

    @router.get("/statistics", response_model=ResearchStatisticsCapabilityCatalogDto)
    def statistics() -> ResearchStatisticsCapabilityCatalogDto:
        return ResearchStatisticsCapabilityCatalogDto(
            statistics=tuple(ResearchStatisticsCapabilityDto.from_model(item) for item in service.statistics())
        )

    @router.get("/dataset-fields", response_model=ResearchDatasetFieldCatalogDto)
    def dataset_fields() -> ResearchDatasetFieldCatalogDto:
        return ResearchDatasetFieldCatalogDto(
            dataset_fields=tuple(
                ResearchDatasetFieldDto(
                    source=source,
                    field_name=contract.column,
                    data_type=contract.data_type.value,
                    semantic_roles=tuple(sorted(contract.semantic_roles)),
                    dimensions=contract.dimensions,
                    unit=contract.unit,
                )
                for source, contract in service.dataset_fields()
            )
        )

    return router


def create_definition_router(service: ResearchDefinitionApiService) -> APIRouter:
    router = APIRouter(prefix="/api/v2/research/definitions", tags=[DEFINITION_ROUTE_TAG])

    @router.post(
        "/resolve",
        response_model=ResearchDefinitionResolutionDto,
        responses=_DEFINITION_ERRORS,
        openapi_extra={
            "x-onlyalpha-agent-operation": {
                "schema_version": 1,
                "tool_class": "RESEARCH_DEFINITION_RESOLVE",
                "recovery_class": "PURE_RESOLVE",
                "requires_product_command_id": False,
                "product_command_id_transport": None,
                "identity_requirements": [],
                "owning_authority_references": [
                    {
                        "reference_kind": "RESEARCH_SPECIFICATION",
                        "reference_schema_version": 1,
                        "locator_kind": "SHA256",
                        "response_field": "specification_fingerprint",
                    }
                ],
            }
        },
    )
    def resolve_definition(request: ResearchDefinitionRequestDto) -> ResearchDefinitionResolutionDto:
        return service.resolve(request)

    return router


__all__ = [
    "DEFINITION_ROUTE_TAG",
    "DISCOVERY_ROUTE_TAG",
    "create_definition_router",
    "create_discovery_router",
]
