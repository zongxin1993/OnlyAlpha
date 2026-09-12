"""Exact Product reads for immutable Search authoring inputs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Protocol

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, ConfigDict

SEARCH_AUTHORING_ROUTE_TAG = "search-authoring"


class OnlySearchAuthoringValue(Protocol):
    def to_dict(self) -> Mapping[str, object]: ...


class OnlySearchAuthoringInputReader(Protocol):
    def load_search_authoring_input_verified(
        self, reference_kind: str, fingerprint: str
    ) -> OnlySearchAuthoringValue: ...


class SearchAuthoringInputDto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: int = 1
    reference_kind: str
    reference_fingerprint: str
    payload: dict[str, object]


KindPath = Annotated[str, Path(pattern=r"^[A-Z][A-Z0-9_]{2,127}$")]
ShaPath = Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")]


def create_search_authoring_router(reader: OnlySearchAuthoringInputReader) -> APIRouter:
    router = APIRouter(prefix="/api/v2/research/search/authoring", tags=[SEARCH_AUTHORING_ROUTE_TAG])

    @router.get(
        "/{reference_kind}/{reference_fingerprint}",
        operation_id="get_exact_search_authoring_input_v2",
        response_model=SearchAuthoringInputDto,
    )
    def get_input(reference_kind: KindPath, reference_fingerprint: ShaPath) -> SearchAuthoringInputDto:
        try:
            value = reader.load_search_authoring_input_verified(reference_kind, reference_fingerprint)
            payload = dict(value.to_dict())
        except Exception as error:
            raise HTTPException(status_code=404, detail="SEARCH_AUTHORING_INPUT_NOT_FOUND") from error
        if reference_fingerprint not in payload.values():
            raise HTTPException(status_code=500, detail="SEARCH_AUTHORING_INPUT_IDENTITY_MISMATCH")
        return SearchAuthoringInputDto(
            reference_kind=reference_kind,
            reference_fingerprint=reference_fingerprint,
            payload=payload,
        )

    return router


__all__ = [name for name in globals() if name.startswith(("Only", "SEARCH", "Search", "create_"))]
