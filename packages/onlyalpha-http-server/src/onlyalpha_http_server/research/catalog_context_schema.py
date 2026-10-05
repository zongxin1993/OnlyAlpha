"""Transport schema for the immutable Exact Catalog Context projection."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from onlyalpha.application.catalog_context import (
    OnlyExactCatalogCalculationReadinessCapabilityV1,
    OnlyExactCatalogContextV1,
    OnlyExactCatalogReadinessProjectionV1,
)
from onlyalpha.calculation.definition import OnlyCalculationBackendKind, OnlyCalculationKind
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.quant_assets.catalog import OnlyQuantAssetKind

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


class ExactCatalogCalculationReadinessCapabilityDto(_Dto):
    schema_version: Literal[1]
    catalog_generation_fingerprint: str = Field(pattern=_SHA)
    provider_id: str = Field(min_length=1)
    provider_version: str = Field(min_length=1)
    provider_kind: OnlyQuantAssetKind
    kind: OnlyCalculationKind
    type_id: str = Field(min_length=1)
    semantic_version: str = Field(min_length=1)
    backend: OnlyCalculationBackendKind
    implementation_fingerprint: str = Field(pattern=_SHA)
    readiness_contract_versions: tuple[Annotated[int, Field(ge=1)], ...]
    capability_fingerprint: str = Field(pattern=_SHA)

    @field_validator("schema_version", mode="before")
    @classmethod
    def require_plain_schema_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("EXACT_CATALOG_CONTEXT_SCHEMA_UNSUPPORTED")
        return value

    @model_validator(mode="after")
    def verify_capability(self) -> Self:
        OnlyExactCatalogCalculationReadinessCapabilityV1.from_dict(self.model_dump(mode="json"))
        return self


class ExactCatalogReadinessProjectionResponseDto(_Dto):
    schema_version: Literal[1]
    catalog_generation_fingerprint: str = Field(pattern=_SHA)
    exact_catalog_context_projection_schema_fingerprint: str = Field(pattern=_SHA)
    exact_catalog_context_projection_fingerprint: str = Field(pattern=_SHA)
    ordered_calculation_readiness_capabilities: tuple[ExactCatalogCalculationReadinessCapabilityDto, ...]
    projection_schema_fingerprint: str = Field(pattern=_SHA)
    projection_fingerprint: str = Field(pattern=_SHA)

    @field_validator("schema_version", mode="before")
    @classmethod
    def require_plain_schema_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("EXACT_CATALOG_CONTEXT_SCHEMA_UNSUPPORTED")
        return value

    @model_validator(mode="after")
    def verify_projection(self) -> Self:
        OnlyExactCatalogReadinessProjectionV1.from_dict(self.model_dump(mode="json"))
        return self

    @classmethod
    def from_model(cls, value: OnlyExactCatalogReadinessProjectionV1) -> ExactCatalogReadinessProjectionResponseDto:
        return cls.model_validate_json(only_canonical_json(value.to_dict()))


__all__ = [
    "LEGACY_EXACT_CATALOG_CONTEXT_PROJECTION_SCHEMA_FINGERPRINT",
    "ExactCatalogContextLegacyResponseDto",
    "ExactCatalogContextResponseDto",
    "ExactCatalogCalculationReadinessCapabilityDto",
    "ExactCatalogReadinessProjectionResponseDto",
]
