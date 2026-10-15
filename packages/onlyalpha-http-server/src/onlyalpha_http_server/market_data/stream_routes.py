"""Thin Product WebSocket adapter."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from starlette.websockets import WebSocketState

from onlyalpha.application.market_data_product import OnlyMarketDataProductError, OnlyMarketDataSourceReferenceV1
from onlyalpha.application.market_data_stream import OnlyMarketDataStreamProductService
from onlyalpha.application.source_read_access import (
    OnlySourceReadAccessError,
    OnlySourceReadPermission,
    OnlySourceReadSession,
)

from ..local_read_access import (
    HANDSHAKE_SECONDS,
    MAX_CONTROL_BYTES,
    OnlyLocalReadIngress,
    only_decode_local_control,
    only_request_read_session,
)
from .stream_schema import (
    MarketDataStreamAuthDto,
    MarketDataStreamAuthenticatedDto,
    MarketDataStreamSubscribeDto,
    market_data_stream_event_adapter,
)


def create_market_data_stream_router(service: OnlyMarketDataStreamProductService) -> APIRouter:
    router = APIRouter(tags=["market-data"])

    @router.websocket("/api/v2/market-data/stream")
    async def stream(websocket: WebSocket) -> None:
        await websocket.accept()
        session = None
        opening = None
        stopping = None
        withdrawing = None
        generation_withdrawing = None
        generation_withdrawn: asyncio.Event | None = websocket.scope.get("onlyalpha.local_read_generation_withdrawn")
        detaching = None
        event_task = None
        access: OnlySourceReadSession | None = only_request_read_session(websocket.scope)
        ingress: OnlyLocalReadIngress | None = websocket.scope.get("onlyalpha.local_read_ingress")
        try:
            if ingress is not None and access is None:
                text = await _control_text(websocket)
                authentication = MarketDataStreamAuthDto.model_validate(only_decode_local_control(text))
                access = ingress.configuration.authority.authenticate("Bearer " + authentication.bearer)
                websocket.scope["onlyalpha.local_read_session"] = access
                await websocket.send_json(
                    MarketDataStreamAuthenticatedDto(schema_version=1, event="AUTHENTICATED").model_dump()
                )
            try:
                request = (
                    MarketDataStreamSubscribeDto.model_validate(
                        only_decode_local_control(await _control_text(websocket))
                    )
                    if ingress is not None
                    else MarketDataStreamSubscribeDto.model_validate(await websocket.receive_json())
                )
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
            access = only_request_read_session(websocket.scope)
            source_reference = OnlyMarketDataSourceReferenceV1(
                reference.integration_id, reference.integration_revision_fingerprint, reference.expected_type_id
            )
            if access is not None:
                access.require_reference(source_reference, OnlySourceReadPermission.REALTIME_PREVIEW)
            stopping = asyncio.create_task(_watch_disconnect(websocket))
            if ingress is not None:
                withdrawing = asyncio.create_task(ingress.withdrawn.wait())
                detaching = asyncio.create_task(websocket.scope["onlyalpha.local_read_detached"].wait())
                if generation_withdrawn is not None:
                    generation_withdrawing = asyncio.create_task(generation_withdrawn.wait())
            opening = asyncio.create_task(
                asyncio.to_thread(
                    service.open,
                    source_reference,
                    instrument_id=request.instrument_id,
                    bar_semantic=request.bar_semantic.to_model(),
                    resume_after_sequence=int(request.resume_after_sequence),
                    resume_plan_fingerprint=request.resume_plan_fingerprint,
                    read_session=access,
                )
            )
            signals: set[asyncio.Task[object]] = {stopping} if withdrawing is None else {stopping, withdrawing}
            if detaching is not None:
                signals.add(detaching)
            if generation_withdrawing is not None:
                signals.add(generation_withdrawing)
            done, _ = await asyncio.wait({opening, *signals}, return_when=asyncio.FIRST_COMPLETED)
            if any(signal in done for signal in signals):
                return
            session = opening.result()
            if access is not None:
                grant = access.require_reference(source_reference, OnlySourceReadPermission.REALTIME_PREVIEW)
                if session.source_id != grant.source_id:
                    raise OnlySourceReadAccessError("LOCAL_READ_FORBIDDEN")
            while True:
                event_task = asyncio.create_task(asyncio.to_thread(session.next_event))
                done, _ = await asyncio.wait({event_task, *signals}, return_when=asyncio.FIRST_COMPLETED)
                if any(signal in done for signal in signals):
                    return
                event = event_task.result()
                if event is not None:
                    if access is not None:
                        grant = access.require_reference(source_reference, OnlySourceReadPermission.REALTIME_PREVIEW)
                        if event.payload.get("source_id", grant.source_id) != grant.source_id:
                            raise OnlySourceReadAccessError("LOCAL_READ_FORBIDDEN")
                    await websocket.send_json(
                        market_data_stream_event_adapter.validate_python(event.to_dict()).model_dump(exclude_unset=True)
                    )
                    if event.event == "ERROR":
                        return
        except WebSocketDisconnect:
            pass
        except OnlySourceReadAccessError:
            await websocket.close(
                code=1012
                if generation_withdrawn is not None
                and generation_withdrawn.is_set()
                and ingress is not None
                and not ingress.withdrawn.is_set()
                else 1008
            )
        except (TimeoutError, ValueError):
            await websocket.close(code=1008)
        except OnlyMarketDataProductError as exc:
            await websocket.send_json(
                {
                    "schema_version": 2,
                    "event": "ERROR",
                    "code": exc.code,
                    "detail": exc.code if ingress is not None else exc.detail,
                }
            )
        except Exception:
            await websocket.send_json({"schema_version": 2, "event": "ERROR", "code": "MARKET_DATA_STREAM_UNAVAILABLE"})
        finally:
            for watcher in (stopping, withdrawing, detaching, generation_withdrawing):
                if watcher is not None:
                    watcher.cancel()
            await asyncio.gather(
                *(t for t in (stopping, withdrawing, detaching, generation_withdrawing) if t is not None),
                return_exceptions=True,
            )
            if session is None and opening is not None:
                try:
                    session = await asyncio.shield(opening)
                except Exception:
                    pass  # Nothing was opened; do not expose provider failure during detachment.
            if session is not None:
                try:
                    await asyncio.shield(asyncio.create_task(asyncio.to_thread(session.close)))
                finally:
                    if event_task is not None:
                        await asyncio.shield(event_task)
            if (
                websocket.application_state is WebSocketState.CONNECTED
                and websocket.client_state is WebSocketState.CONNECTED
            ):
                await websocket.close(
                    code=1008
                    if ingress is not None and ingress.withdrawn.is_set()
                    else 1012
                    if generation_withdrawn is not None and generation_withdrawn.is_set()
                    else 1000
                )

    return router


async def _control_text(websocket: WebSocket) -> str:
    message = await asyncio.wait_for(websocket.receive(), HANDSHAKE_SECONDS)
    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(message.get("code", 1000))
    text = message.get("text")
    if not isinstance(text, str):
        raise ValueError("LOCAL_READ_CONTROL_INVALID")
    if len(text.encode("utf-8")) > MAX_CONTROL_BYTES:
        raise ValueError("LOCAL_READ_CONTROL_INVALID")
    return text


async def _watch_disconnect(websocket: WebSocket) -> None:
    # Exactly one subscription per connection. Any further application frame terminates it.
    await websocket.receive()


__all__ = ["create_market_data_stream_router"]
