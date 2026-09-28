"""Thin Product WebSocket adapter."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from onlyalpha.application.market_data_product import OnlyMarketDataProductError, OnlyMarketDataSourceReferenceV1
from onlyalpha.application.market_data_stream import OnlyMarketDataStreamProductService

from .stream_schema import MarketDataStreamSubscribeDto, market_data_stream_event_adapter


def create_market_data_stream_router(service: OnlyMarketDataStreamProductService) -> APIRouter:
    router = APIRouter(tags=["market-data"])

    @router.websocket("/api/v2/market-data/stream")
    async def stream(websocket: WebSocket) -> None:
        await websocket.accept()
        session = None
        try:
            try:
                request = MarketDataStreamSubscribeDto.model_validate(await websocket.receive_json())
            except ValidationError as exc:
                code = (
                    "MARKET_DATA_RESUME_PLAN_MISMATCH"
                    if any(
                        error["loc"] == ()
                        and str(error.get("ctx", {}).get("error")) == "MARKET_DATA_RESUME_PLAN_MISMATCH"
                        for error in exc.errors()
                    )
                    else "MARKET_DATA_STREAM_REQUEST_INVALID"
                )
                await websocket.send_json({"schema_version": 2, "event": "ERROR", "code": code})
                return
            except ValueError:
                await websocket.send_json(
                    {"schema_version": 2, "event": "ERROR", "code": "MARKET_DATA_STREAM_REQUEST_INVALID"}
                )
                return
            reference = request.source_reference
            session = await asyncio.to_thread(
                service.open,
                OnlyMarketDataSourceReferenceV1(
                    reference.integration_id,
                    reference.integration_revision_fingerprint,
                    reference.expected_type_id,
                ),
                instrument_id=request.instrument_id,
                bar_semantic=request.bar_semantic.to_model(),
                resume_after_sequence=int(request.resume_after_sequence),
                resume_plan_fingerprint=request.resume_plan_fingerprint,
            )
            while True:
                event = await asyncio.to_thread(session.next_event)
                if event is not None:
                    await websocket.send_json(
                        market_data_stream_event_adapter.validate_python(event.to_dict()).model_dump(exclude_none=True)
                    )
                    if event.event == "ERROR":
                        return
        except WebSocketDisconnect:
            pass
        except OnlyMarketDataProductError as exc:
            await websocket.send_json({"schema_version": 2, "event": "ERROR", "code": exc.code, "detail": exc.detail})
        except Exception:
            await websocket.send_json({"schema_version": 2, "event": "ERROR", "code": "MARKET_DATA_STREAM_UNAVAILABLE"})
        finally:
            if session is not None:
                await asyncio.to_thread(session.close)

    return router


__all__ = ["create_market_data_stream_router"]
