"""Transport schema for the immutable Exact Catalog Context projection."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from onlyalpha.application.catalog_context import OnlyExactCatalogContextV1
from onlyalpha.canonical import only_canonical_fingerprint

_SHA = r"^[0-9a-f]{64}$"
LEGACY_EXACT_CATALOG_CONTEXT_PROJECTION_SCHEMA_FINGERPRINT = (
    "169a7c181f87fdd4293165866d8eede19f1f54db12dec44c78d19c922c800a24"
)


class _Dto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class ExactCatalogContextResponseDto(_Dto):
    schema_version: Literal[1]
    catalog_generation_fingerprint: str = Field(
        pattern=_SHA,
        json_schema_extra={
            "x-onlyalpha-reference-kind": "CATALOG_GENERATION",
            "x-onlyalpha-reference-schema-version": 1,
            "x-onlyalpha-reference-locator-kind": "SHA256",
        },
    )
    ordered_providers: tuple[dict[str, JsonValue], ...]
    ordered_calculation_capabilities: tuple[dict[str, JsonValue], ...]
    ordered_registered_universes: tuple[dict[str, JsonValue], ...]
    ordered_dataset_field_contracts: tuple[dict[str, JsonValue], ...]
    ordered_statistics_capabilities: tuple[dict[str, JsonValue], ...]
    projection_schema_fingerprint: str = Field(pattern=_SHA)
    projection_fingerprint: str = Field(pattern=_SHA)

    @classmethod
    def from_model(cls, value: OnlyExactCatalogContextV1) -> ExactCatalogContextResponseDto:
        payload = value.to_dict()
        return cls(
            schema_version=1,
            catalog_generation_fingerprint=value.catalog_generation_fingerprint,
            ordered_providers=tuple(payload["ordered_providers"]),  # type: ignore[arg-type]
            ordered_calculation_capabilities=tuple(payload["ordered_calculation_capabilities"]),  # type: ignore[arg-type]
            ordered_registered_universes=tuple(payload["ordered_registered_universes"]),  # type: ignore[arg-type]
            ordered_dataset_field_contracts=tuple(payload["ordered_dataset_field_contracts"]),  # type: ignore[arg-type]
            ordered_statistics_capabilities=tuple(payload["ordered_statistics_capabilities"]),  # type: ignore[arg-type]
            projection_schema_fingerprint=value.projection_schema_fingerprint,
            projection_fingerprint=value.projection_fingerprint,
        )


class ExactCatalogContextLegacyResponseDto(_Dto):
    """Frozen compatibility projection; not sufficient for Agent decisions."""

    schema_version: Literal[1]
    catalog_generation_fingerprint: str = Field(pattern=_SHA)
    ordered_providers: tuple[dict[str, JsonValue], ...]
    ordered_calculation_capabilities: tuple[dict[str, JsonValue], ...]
    projection_schema_fingerprint: str = Field(pattern=_SHA)
    projection_fingerprint: str = Field(pattern=_SHA)

    @classmethod
    def from_model(cls, value: OnlyExactCatalogContextV1) -> ExactCatalogContextLegacyResponseDto:
        legacy = {
            "schema_version": 1,
            "catalog_generation_fingerprint": value.catalog_generation_fingerprint,
            "ordered_providers": tuple(item.to_dict() for item in value.ordered_providers),
            "ordered_calculation_capabilities": tuple(
                item.to_dict() for item in value.ordered_calculation_capabilities
            ),
            "projection_schema_fingerprint": LEGACY_EXACT_CATALOG_CONTEXT_PROJECTION_SCHEMA_FINGERPRINT,
        }

        return cls(
            **legacy,  # type: ignore[arg-type]
            projection_fingerprint=only_canonical_fingerprint(
                {"domain": "onlyalpha.exact-catalog-context-projection", **legacy}
            ),
        )


__all__ = [
    "LEGACY_EXACT_CATALOG_CONTEXT_PROJECTION_SCHEMA_FINGERPRINT",
    "ExactCatalogContextLegacyResponseDto",
    "ExactCatalogContextResponseDto",
]
