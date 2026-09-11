"""Exact-addressed Catalog Generation Product projection."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path

from onlyalpha.application.catalog_context import OnlyExactCatalogContextQueryService

from .catalog_context_schema import ExactCatalogContextResponseDto

EXACT_CATALOG_ROUTE_TAG = "exact-catalog-context"
CatalogGenerationPath = Annotated[
    str,
    Path(
        pattern=r"^[0-9a-f]{64}$",
        json_schema_extra={
            "x-onlyalpha-reference-kind": "CATALOG_GENERATION",
            "x-onlyalpha-reference-schema-version": 1,
            "x-onlyalpha-reference-locator-kind": "SHA256",
        },
    ),
]


def create_exact_catalog_context_router(service: OnlyExactCatalogContextQueryService) -> APIRouter:
    router = APIRouter(prefix="/api/v2/research/catalog-context", tags=[EXACT_CATALOG_ROUTE_TAG])

    @router.get(
        "/{catalog_generation_fingerprint}",
        operation_id="get_exact_catalog_context_v2",
        response_model=ExactCatalogContextResponseDto,
        openapi_extra={
            "x-onlyalpha-agent-operation": {
                "schema_version": 1,
                "tool_class": "EXACT_CATALOG_CONTEXT_QUERY",
                "recovery_class": "IMMUTABLE_EXACT_QUERY",
                "requires_product_command_id": False,
                "product_command_id_transport": None,
                "identity_requirements": ["catalog_generation_fingerprint"],
                "owning_authority_references": [
                    {
                        "reference_kind": "CATALOG_GENERATION",
                        "reference_schema_version": 1,
                        "locator_kind": "SHA256",
                        "response_field": "catalog_generation_fingerprint",
                    }
                ],
            }
        },
    )
    def get_exact_catalog_context(
        catalog_generation_fingerprint: CatalogGenerationPath,
    ) -> ExactCatalogContextResponseDto:
        return ExactCatalogContextResponseDto.from_model(
            service.get_exact_catalog_context(catalog_generation_fingerprint)
        )

    return router


__all__ = ["EXACT_CATALOG_ROUTE_TAG", "create_exact_catalog_context_router"]
