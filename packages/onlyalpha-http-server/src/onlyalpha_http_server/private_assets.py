"""Read-only Product API for DB-native Private Factor and Strategy assets."""

from __future__ import annotations

from datetime import UTC
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, FastAPI, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from onlyalpha.application.private_asset_product import (
    OnlyPrivateAssetExactReadFailure,
    OnlyPrivateAssetExactReadMismatch,
    OnlyPrivateAssetExactRevisionUnavailable,
    OnlyPrivateAssetProductError,
    OnlyPrivateAssetProductService,
    OnlyProductAssetLocatorV1,
    OnlyProductAssetProjectionCompleteness,
    OnlyProductAssetRegistryEntryV1,
    OnlyProductAssetRegistrySnapshotV1,
    OnlyProductAssetSearchProjectionCorrupt,
    OnlyProductAssetSearchProjectionService,
    OnlyProductAssetSearchProjectionUnavailable,
    OnlyProductAssetSearchQueryV1,
    OnlyProductAssetSearchResultV1,
    OnlyProductAssetSearchStatus,
)
from onlyalpha.quant_assets.private import (
    OnlyPrivateAssetAuthorityUnavailableError,
    OnlyPrivateAssetCorruptError,
    OnlyPrivateAssetError,
    OnlyPrivateAssetKind,
    OnlyPrivateAssetNotFoundError,
    OnlyPrivateFactorRevision,
    OnlyPrivateStrategyRevision,
)

PRIVATE_ASSET_ROUTE_TAG = "private-asset-product"
_SHA = r"^[0-9a-f]{64}$"
_FACTOR_ID = r"^private\.factor\.[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"
_STRATEGY_ID = r"^private\.strategy\.[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"


class _Dto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class PrivateAssetErrorDto(_Dto):
    code: str
    detail: str


class PrivateAssetErrorEnvelopeDto(_Dto):
    error: PrivateAssetErrorDto


class PrivateAssetLocatorDto(_Dto):
    private_asset_kind: OnlyPrivateAssetKind
    private_asset_id: str
    revision_fingerprint: str = Field(pattern=_SHA)
    content_fingerprint: str = Field(pattern=_SHA)

    @classmethod
    def from_model(cls, value: OnlyProductAssetLocatorV1) -> PrivateAssetLocatorDto:
        return cls(
            private_asset_kind=value.private_asset_kind,
            private_asset_id=value.private_asset_id,
            revision_fingerprint=value.revision_fingerprint,
            content_fingerprint=value.content_fingerprint,
        )


class PrivateAssetRegistryEntryDto(_Dto):
    locator: PrivateAssetLocatorDto
    semantic_version: str
    description: str
    category: str | None
    tags: tuple[str, ...]

    @classmethod
    def from_model(cls, value: OnlyProductAssetRegistryEntryV1) -> PrivateAssetRegistryEntryDto:
        return cls(
            locator=PrivateAssetLocatorDto.from_model(value.locator),
            semantic_version=value.semantic_version,
            description=value.description,
            category=value.category,
            tags=value.tags,
        )


class PrivateAssetRegistryDto(_Dto):
    schema_version: Literal[1] = 1
    registry_fingerprint: str = Field(pattern=_SHA)
    entries: tuple[PrivateAssetRegistryEntryDto, ...]

    @classmethod
    def from_model(cls, value: OnlyProductAssetRegistrySnapshotV1) -> PrivateAssetRegistryDto:
        return cls(
            registry_fingerprint=value.registry_fingerprint,
            entries=tuple(PrivateAssetRegistryEntryDto.from_model(item) for item in value.entries),
        )


class PrivateAssetSearchResultDto(_Dto):
    schema_version: Literal[1] = 1
    status: OnlyProductAssetSearchStatus
    results: tuple[PrivateAssetRegistryEntryDto, ...]
    projection_fingerprint: str | None = Field(default=None, pattern=_SHA)
    registry_fingerprint: str | None = Field(default=None, pattern=_SHA)
    completeness: OnlyProductAssetProjectionCompleteness | None
    built_at: str | None
    projection_stale: bool

    @classmethod
    def from_model(cls, value: OnlyProductAssetSearchResultV1) -> PrivateAssetSearchResultDto:
        return cls(
            status=value.status,
            results=tuple(PrivateAssetRegistryEntryDto.from_model(item) for item in value.results),
            projection_fingerprint=value.projection_fingerprint,
            registry_fingerprint=value.registry_fingerprint,
            completeness=value.completeness,
            built_at=(
                None if value.built_at is None else value.built_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
            ),
            projection_stale=value.projection_stale,
        )


class PrivateFactorRevisionDto(_Dto):
    schema_version: Literal[1]
    factor_id: str
    semantic_version: str
    revision_fingerprint: str = Field(pattern=_SHA)
    parent_revision_fingerprint: str | None = Field(pattern=_SHA)
    source_text: str
    source_sha256: str = Field(pattern=_SHA)
    factor_api_version: Literal[1]
    factor_api_contract_fingerprint: str = Field(pattern=_SHA)
    input_contract: dict[str, JsonValue]
    parameter_contract: dict[str, JsonValue]
    output_contract: dict[str, JsonValue]
    description: str
    economic_rationale: str
    category: str
    tags: tuple[str, ...]

    @classmethod
    def from_model(cls, value: OnlyPrivateFactorRevision) -> PrivateFactorRevisionDto:
        payload = value.to_dict()
        return cls(
            schema_version=1,
            factor_id=value.factor_id,
            semantic_version=value.semantic_version,
            revision_fingerprint=value.revision_fingerprint,
            parent_revision_fingerprint=value.parent_revision_fingerprint,
            source_text=value.source_text,
            source_sha256=value.source_sha256,
            factor_api_version=1,
            factor_api_contract_fingerprint=value.factor_api_contract_fingerprint,
            input_contract=cast(dict[str, JsonValue], payload["input_contract"]),
            parameter_contract=cast(dict[str, JsonValue], payload["parameter_contract"]),
            output_contract=cast(dict[str, JsonValue], payload["output_contract"]),
            description=value.description,
            economic_rationale=value.economic_rationale,
            category=value.category,
            tags=value.tags,
        )


class PrivateStrategyRevisionDto(_Dto):
    schema_version: Literal[1]
    strategy_id: str
    semantic_version: str
    revision_fingerprint: str = Field(pattern=_SHA)
    parent_revision_fingerprint: str | None = Field(pattern=_SHA)
    definition: dict[str, JsonValue]
    definition_fingerprint: str = Field(pattern=_SHA)
    description: str
    tags: tuple[str, ...]

    @classmethod
    def from_model(cls, value: OnlyPrivateStrategyRevision) -> PrivateStrategyRevisionDto:
        return cls(
            schema_version=1,
            strategy_id=value.strategy_id,
            semantic_version=value.semantic_version,
            revision_fingerprint=value.revision_fingerprint,
            parent_revision_fingerprint=value.parent_revision_fingerprint,
            definition=cast(dict[str, JsonValue], value.to_dict()["definition"]),
            definition_fingerprint=value.definition_fingerprint,
            description=value.description,
            tags=value.tags,
        )


FactorIdPath = Annotated[str, Path(pattern=_FACTOR_ID)]
StrategyIdPath = Annotated[str, Path(pattern=_STRATEGY_ID)]
RevisionPath = Annotated[str, Path(pattern=_SHA)]
ContentFingerprint = Annotated[str, Query(pattern=_SHA)]
_ERRORS: dict[int | str, dict[str, Any]] = {
    status: {"model": PrivateAssetErrorEnvelopeDto} for status in (400, 404, 409, 500, 503)
}


def install_private_asset_error_handlers(app: FastAPI) -> None:
    async def handler(_request: Request, error: Exception) -> JSONResponse:
        if isinstance(error, OnlyPrivateAssetExactRevisionUnavailable | OnlyPrivateAssetNotFoundError):
            status = 404
        elif isinstance(error, OnlyPrivateAssetExactReadMismatch):
            status = 409
        elif isinstance(error, OnlyPrivateAssetAuthorityUnavailableError | OnlyProductAssetSearchProjectionUnavailable):
            status = 503
        elif isinstance(
            error,
            OnlyPrivateAssetExactReadFailure | OnlyProductAssetSearchProjectionCorrupt | OnlyPrivateAssetCorruptError,
        ):
            status = 500
        else:
            status = 400
        code = cast(OnlyPrivateAssetProductError | OnlyPrivateAssetError, error).code
        body = PrivateAssetErrorEnvelopeDto(
            error=PrivateAssetErrorDto(code=code, detail=getattr(error, "detail", "") or code)
        )
        return JSONResponse(status_code=status, content=body.model_dump(mode="json"))

    app.add_exception_handler(OnlyPrivateAssetProductError, handler)
    app.add_exception_handler(OnlyPrivateAssetError, handler)


def create_private_asset_router(
    product: OnlyPrivateAssetProductService,
    search: OnlyProductAssetSearchProjectionService,
) -> APIRouter:
    router = APIRouter(prefix="/api/v2/private-assets", tags=[PRIVATE_ASSET_ROUTE_TAG])

    @router.get(
        "",
        operation_id="browse_current_private_assets_v2",
        response_model=PrivateAssetRegistryDto,
        responses=_ERRORS,
    )
    def browse_current() -> PrivateAssetRegistryDto:
        return PrivateAssetRegistryDto.from_model(product.current_registry())

    @router.get(
        "/search",
        operation_id="search_private_assets_v2",
        response_model=PrivateAssetSearchResultDto,
        responses=_ERRORS,
    )
    def search_assets(
        text: Annotated[str | None, Query()] = None,
        kind: OnlyPrivateAssetKind | None = None,
        category: Annotated[str | None, Query()] = None,
        tag: Annotated[str | None, Query()] = None,
    ) -> PrivateAssetSearchResultDto:
        return PrivateAssetSearchResultDto.from_model(
            search.search(OnlyProductAssetSearchQueryV1(text=text, kind=kind, category=category, tag=tag))
        )

    @router.get(
        "/factors/{factor_id}/revisions/{revision_fingerprint}",
        operation_id="get_exact_private_factor_revision_v2",
        response_model=PrivateFactorRevisionDto,
        responses=_ERRORS,
    )
    def get_factor(
        factor_id: FactorIdPath,
        revision_fingerprint: RevisionPath,
        content_fingerprint: ContentFingerprint,
    ) -> PrivateFactorRevisionDto:
        revision = product.read_exact(
            OnlyProductAssetLocatorV1(
                OnlyPrivateAssetKind.FACTOR,
                factor_id,
                revision_fingerprint,
                content_fingerprint,
            )
        )
        if not isinstance(revision, OnlyPrivateFactorRevision):
            raise TypeError("PRIVATE_ASSET_EXACT_READ_KIND_MISMATCH")
        return PrivateFactorRevisionDto.from_model(revision)

    @router.get(
        "/strategies/{strategy_id}/revisions/{revision_fingerprint}",
        operation_id="get_exact_private_strategy_revision_v2",
        response_model=PrivateStrategyRevisionDto,
        responses=_ERRORS,
    )
    def get_strategy(
        strategy_id: StrategyIdPath,
        revision_fingerprint: RevisionPath,
        content_fingerprint: ContentFingerprint,
    ) -> PrivateStrategyRevisionDto:
        revision = product.read_exact(
            OnlyProductAssetLocatorV1(
                OnlyPrivateAssetKind.STRATEGY,
                strategy_id,
                revision_fingerprint,
                content_fingerprint,
            )
        )
        if not isinstance(revision, OnlyPrivateStrategyRevision):
            raise TypeError("PRIVATE_ASSET_EXACT_READ_KIND_MISMATCH")
        return PrivateStrategyRevisionDto.from_model(revision)

    return router


__all__ = [
    "PRIVATE_ASSET_ROUTE_TAG",
    "create_private_asset_router",
    "install_private_asset_error_handlers",
]
