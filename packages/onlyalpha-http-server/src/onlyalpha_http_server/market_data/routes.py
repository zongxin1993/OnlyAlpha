"""Thin Market Data Product HTTP adapter over the canonical Query/Command boundary."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from onlyalpha.application.market_data_product import (
    OnlyMarketDataProductError,
    OnlyMarketDataProductService,
    OnlyMarketDataSourceSelectionV1,
)

from .schema import (
    MarketDataAcquisitionDto,
    MarketDataAcquisitionRequestDto,
    MarketDataBarsDto,
    MarketDataErrorDto,
    MarketDataErrorEnvelopeDto,
    MarketDataInstrumentDto,
    MarketDataInstrumentListDto,
    MarketDataSourceSelectionDto,
)

MARKET_DATA_ROUTE_TAG = "market-data"

_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    400: {"model": MarketDataErrorEnvelopeDto},
    404: {"model": MarketDataErrorEnvelopeDto},
    409: {"model": MarketDataErrorEnvelopeDto},
    503: {"model": MarketDataErrorEnvelopeDto},
}


def create_market_data_router(service: OnlyMarketDataProductService) -> APIRouter:
    router = APIRouter(tags=[MARKET_DATA_ROUTE_TAG])

    @router.get("/api/v2/market/instruments", response_model=MarketDataInstrumentListDto, responses=_ERROR_RESPONSES)
    def list_instruments(
        integration_id: str,
        integration_revision_fingerprint: str,
        type_id: str,
        source_id: str,
        query: str = "",
        limit: int = Query(default=25, ge=1, le=25),
    ) -> MarketDataInstrumentListDto:
        selection = _selection(integration_id, integration_revision_fingerprint, type_id, source_id)
        instruments = service.list_instruments(selection, query=query, limit=limit)
        return MarketDataInstrumentListDto(
            schema_version=1,
            source_selection=MarketDataSourceSelectionDto.from_model(selection),
            source_id=source_id,
            type_id=type_id,
            instruments=tuple(MarketDataInstrumentDto.from_model(item) for item in instruments),
        )

    @router.get("/api/v2/market-data/bars", response_model=MarketDataBarsDto, responses=_ERROR_RESPONSES)
    def query_bars(
        integration_id: str,
        integration_revision_fingerprint: str,
        type_id: str,
        source_id: str,
        instrument_id: str,
        start_ns: int,
        end_ns: int,
        bar_specification: str = "1m",
    ) -> MarketDataBarsDto:
        selection = _selection(integration_id, integration_revision_fingerprint, type_id, source_id)
        return MarketDataBarsDto.from_model(
            service.query_bars(
                selection,
                instrument_id=instrument_id,
                start_ns=start_ns,
                end_ns=end_ns,
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
                request.source_selection.to_model(),
                instrument_id=request.instrument_id,
                start_ns=request.start_ns,
                end_ns=request.end_ns,
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
        type_id: str,
        source_id: str,
    ) -> MarketDataAcquisitionDto:
        selection = _selection(integration_id, integration_revision_fingerprint, type_id, source_id)
        return MarketDataAcquisitionDto.from_model(service.acquisition_status(selection, acquisition_id))

    return router


def market_data_error_response(error: OnlyMarketDataProductError) -> JSONResponse:
    phase: Literal["QUERY", "COMMAND"] = "COMMAND" if error.code.startswith("MARKET_DATA_ACQUISITION") else "QUERY"
    if error.code.endswith("NOT_FOUND"):
        status = 404
    elif error.code.endswith("_UNAVAILABLE") or error.code.endswith("_UNRESOLVED"):
        status = 503
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


def _selection(
    integration_id: str,
    integration_revision_fingerprint: str,
    type_id: str,
    source_id: str,
) -> OnlyMarketDataSourceSelectionV1:
    return OnlyMarketDataSourceSelectionV1(
        integration_id,
        integration_revision_fingerprint,
        type_id,
        source_id,
    )


__all__ = [
    "MARKET_DATA_ROUTE_TAG",
    "create_market_data_router",
    "market_data_error_response",
    "market_data_request_validation_error_response",
]
