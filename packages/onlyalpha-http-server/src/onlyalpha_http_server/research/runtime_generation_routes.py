"""Read-only Product projection of the Runtime Generation eligible for new work."""

from __future__ import annotations

from typing import Literal, Protocol

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

RUNTIME_GENERATION_ROUTE_TAG = "runtime-generation"


class OnlyRuntimeGenerationProjection(Protocol):
    @property
    def active_for_new_work(self) -> str | None: ...


class OnlyRuntimeGenerationProjectionReader(Protocol):
    def projection(self) -> OnlyRuntimeGenerationProjection: ...


class ActiveRuntimeGenerationDto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    runtime_generation_fingerprint: str


def create_runtime_generation_router(reader: OnlyRuntimeGenerationProjectionReader) -> APIRouter:
    router = APIRouter(prefix="/api/v2/research/runtime-generations", tags=[RUNTIME_GENERATION_ROUTE_TAG])

    @router.get(
        "/active",
        operation_id="get_active_runtime_generation_v2",
        response_model=ActiveRuntimeGenerationDto,
    )
    def get_active() -> ActiveRuntimeGenerationDto:
        fingerprint = reader.projection().active_for_new_work
        if fingerprint is None:
            raise HTTPException(status_code=503, detail="RUNTIME_GENERATION_NOT_ACTIVE")
        return ActiveRuntimeGenerationDto(runtime_generation_fingerprint=fingerprint)

    return router


__all__ = [name for name in globals() if name.startswith(("Active", "Only", "RUNTIME", "create_"))]
