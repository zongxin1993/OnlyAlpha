"""Versioned owner Watchlist configuration; read-only Source credentials grant no writes."""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from onlyalpha.application.market_data_product import OnlyMarketDataSourceReferenceV1
from onlyalpha.application.source_read_access import OnlySourceReadAccessError, OnlySourceReadSession
from onlyalpha.application.watchlists import OnlyWatchlist, OnlyWatchlistBook, OnlyWatchlistError, OnlyWatchlistService


class WatchlistSourceDto(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    integration_id: str = Field(min_length=1, max_length=256)
    integration_revision_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_type_id: str = Field(min_length=1, max_length=256)


class WatchlistDto(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    list_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
    name: str = Field(min_length=1, max_length=64)
    source: WatchlistSourceDto
    instrument_ids: tuple[str, ...] = Field(max_length=100, strict=False)

    def to_model(self) -> OnlyWatchlist:
        return OnlyWatchlist(
            self.list_id, self.name, OnlyMarketDataSourceReferenceV1(**self.source.model_dump()), self.instrument_ids
        )


class WatchlistBookDto(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schema_version: Literal[1] = 1
    version: int = Field(ge=0)
    lists: tuple[WatchlistDto, ...] = Field(max_length=20, strict=False)

    @classmethod
    def from_model(cls, book: OnlyWatchlistBook) -> WatchlistBookDto:
        return cls(version=book.version, lists=tuple(WatchlistDto.model_validate(asdict(item)) for item in book.lists))


class SaveWatchlistsDto(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schema_version: Literal[1]
    command_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
    expected_version: int = Field(ge=0)
    lists: tuple[WatchlistDto, ...] = Field(max_length=20, strict=False)


class WatchlistErrorDto(BaseModel):
    code: str


class WatchlistErrorEnvelopeDto(BaseModel):
    error: WatchlistErrorDto


def _owner(request: Request) -> OnlySourceReadSession:
    session = request.scope.get("onlyalpha.watchlist_owner_session")
    if not isinstance(session, OnlySourceReadSession):
        raise OnlySourceReadAccessError("LOCAL_READ_FORBIDDEN")
    session.check_active()
    return session


def create_watchlist_router(service: OnlyWatchlistService) -> APIRouter:
    router = APIRouter(tags=["watchlists"])
    responses: dict[int | str, dict[str, object]] = {
        400: {"model": WatchlistErrorEnvelopeDto},
        403: {"model": WatchlistErrorEnvelopeDto},
        409: {"model": WatchlistErrorEnvelopeDto},
        503: {"model": WatchlistErrorEnvelopeDto},
    }

    @router.get("/api/v2/watchlists", response_model=WatchlistBookDto, responses=responses)
    def read(request: Request) -> WatchlistBookDto:
        _owner(request)
        return WatchlistBookDto.from_model(service.read())

    @router.put("/api/v2/watchlists", response_model=WatchlistBookDto, responses=responses)
    def save(request: Request, body: SaveWatchlistsDto) -> WatchlistBookDto:
        session = _owner(request)
        return WatchlistBookDto.from_model(
            service.save(body.command_id, body.expected_version, tuple(item.to_model() for item in body.lists), session)
        )

    @router.get("/api/v2/watchlists/commands/{command_id}", response_model=WatchlistBookDto | None, responses=responses)
    def command(
        request: Request,
        command_id: str = Path(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
    ) -> WatchlistBookDto | None:
        _owner(request)
        result = service.command(command_id)
        return None if result is None else WatchlistBookDto.from_model(result)

    return router


def watchlist_error_response(error: OnlyWatchlistError) -> JSONResponse:
    status = (
        503
        if error.code.endswith(("UNAVAILABLE", "CORRUPT", "UNKNOWN"))
        else 409
        if error.code.endswith("CONFLICT")
        else 400
    )
    return JSONResponse(status_code=status, content={"error": {"code": error.code}})
