"""Transport schema for the immutable Exact Catalog Context projection."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from onlyalpha.application.catalog_context import OnlyExactCatalogContextV1

_SHA = r"^[0-9a-f]{64}$"


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
            projection_schema_fingerprint=value.projection_schema_fingerprint,
            projection_fingerprint=value.projection_fingerprint,
        )


__all__ = ["ExactCatalogContextResponseDto"]
