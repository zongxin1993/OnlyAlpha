"""Thin Market Data Product HTTP adapter over the canonical Query/Command boundary."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from onlyalpha.application.market_data_product import (
    OnlyMarketDataProductError,
    OnlyMarketDataProductService,
    OnlyMarketDataSourceReferenceV1,
)

from .schema import (
    MarketDataAcquisitionDto,
    MarketDataAcquisitionRequestDto,
    MarketDataBarsDto,
    MarketDataErrorDto,
    MarketDataErrorEnvelopeDto,
    MarketDataInstrumentListDto,
    MarketDataSourceListDto,
    MarketDataSourceProjectionDto,
)

MARKET_DATA_ROUTE_TAG = "market-data"

_NANOSECONDS = r"^(?:0|[1-9][0-9]*)$"
_Nanoseconds = Annotated[str, Query(pattern=_NANOSECONDS)]

_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    400: {"model": MarketDataErrorEnvelopeDto},
    404: {"model": MarketDataErrorEnvelopeDto},
    409: {"model": MarketDataErrorEnvelopeDto},
    503: {"model": MarketDataErrorEnvelopeDto},
}


def create_market_data_router(service: OnlyMarketDataProductService) -> APIRouter:
    router = APIRouter(tags=[MARKET_DATA_ROUTE_TAG])

    @router.get("/api/v2/market-data/sources", response_model=MarketDataSourceListDto, responses=_ERROR_RESPONSES)
    def list_sources() -> MarketDataSourceListDto:
        return MarketDataSourceListDto(
            schema_version=1,
            sources=tuple(MarketDataSourceProjectionDto.from_model(item) for item in service.list_sources()),
        )

    @router.get("/api/v2/market/instruments", response_model=MarketDataInstrumentListDto, responses=_ERROR_RESPONSES)
    def list_instruments(
        integration_id: str,
        integration_revision_fingerprint: str,
        expected_type_id: str | None = None,
        query: str = "",
        limit: int = Query(default=25, ge=1, le=25),
    ) -> MarketDataInstrumentListDto:
        return MarketDataInstrumentListDto.from_model(
            service.list_instruments(
                _reference(integration_id, integration_revision_fingerprint, expected_type_id),
                query=query,
                limit=limit,
            )
        )

    @router.get("/api/v2/market-data/bars", response_model=MarketDataBarsDto, responses=_ERROR_RESPONSES)
    def query_bars(
        integration_id: str,
        integration_revision_fingerprint: str,
        instrument_id: str,
        start_ns: _Nanoseconds,
        end_ns: _Nanoseconds,
        bar_specification: str = "1m",
        expected_type_id: str | None = None,
    ) -> MarketDataBarsDto:
        return MarketDataBarsDto.from_model(
            service.query_bars(
                _reference(integration_id, integration_revision_fingerprint, expected_type_id),
                instrument_id=instrument_id,
                start_ns=int(start_ns),
                end_ns=int(end_ns),
                bar_specification=bar_specification,
            )
        )

    @router.post(
        "/api/v2/market-data/acquisitions",
        status_code=201,
        response_model=MarketDataAcquisitionDto,
        responses=_ERROR_RESPONSES,
    )
    def create_acquisition(request: MarketDataAcquisitionRequestDto) -> MarketDataAcquisitionDto:
        return MarketDataAcquisitionDto.from_model(
            service.acquire_bars(
                request.source_reference.to_model(),
                instrument_id=request.instrument_id,
                start_ns=int(request.start_ns),
                end_ns=int(request.end_ns),
                bar_specification=request.bar_specification,
            )
        )

    @router.get(
        "/api/v2/market-data/acquisitions/{acquisition_id}",
        response_model=MarketDataAcquisitionDto,
        responses=_ERROR_RESPONSES,
    )
    def get_acquisition(
        acquisition_id: str,
        integration_id: str,
        integration_revision_fingerprint: str,
        expected_type_id: str | None = None,
    ) -> MarketDataAcquisitionDto:
        return MarketDataAcquisitionDto.from_model(
            service.acquisition_status(
                _reference(integration_id, integration_revision_fingerprint, expected_type_id), acquisition_id
            )
        )

    return router


def market_data_error_response(error: OnlyMarketDataProductError) -> JSONResponse:
    phase: Literal["QUERY", "COMMAND"] = "COMMAND" if error.code.startswith("MARKET_DATA_ACQUISITION") else "QUERY"
    if error.code.endswith("NOT_FOUND"):
        status = 404
    elif error.code.endswith("_UNAVAILABLE") or error.code.endswith("_UNRESOLVED"):
        status = 503
    elif error.code.endswith("_CORRUPT"):
        status = 500
    elif error.code.endswith("_CONFLICT"):
        status = 409
    else:
        status = 400
    body = MarketDataErrorEnvelopeDto(error=MarketDataErrorDto(phase=phase, code=error.code, detail=error.detail))
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


def market_data_request_validation_error_response() -> JSONResponse:
    body = MarketDataErrorEnvelopeDto(
        error=MarketDataErrorDto(
            phase="QUERY",
            code="MARKET_DATA_REQUEST_INVALID",
            detail="HTTP request validation failed",
        )
    )
    return JSONResponse(status_code=400, content=body.model_dump(mode="json"))


def _reference(
    integration_id: str, integration_revision_fingerprint: str, expected_type_id: str | None
) -> OnlyMarketDataSourceReferenceV1:
    return OnlyMarketDataSourceReferenceV1(
        integration_id,
        integration_revision_fingerprint,
        expected_type_id,
    )


__all__ = [
    "MARKET_DATA_ROUTE_TAG",
    "create_market_data_router",
    "market_data_error_response",
    "market_data_request_validation_error_response",
]
