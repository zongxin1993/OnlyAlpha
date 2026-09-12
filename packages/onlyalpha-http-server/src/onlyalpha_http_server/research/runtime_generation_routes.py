"""Read-only Product projection of the Runtime Generation eligible for new work."""

from __future__ import annotations

from typing import Annotated, Literal, Protocol

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, ConfigDict

RUNTIME_GENERATION_ROUTE_TAG = "runtime-generation"
ShaPath = Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")]


class OnlyRuntimeGenerationProjection(Protocol):
    @property
    def active_for_new_work(self) -> str | None: ...


class OnlyRuntimeGenerationProjectionReader(Protocol):
    def projection(self) -> OnlyRuntimeGenerationProjection: ...

    def require_runtime_generation(self, runtime_generation_fingerprint: str) -> object: ...


class ActiveRuntimeGenerationDto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    runtime_generation_fingerprint: str


class ExactRuntimeGenerationDto(BaseModel):
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

    @router.get(
        "/{runtime_generation_fingerprint}",
        operation_id="get_exact_runtime_generation_v2",
        response_model=ExactRuntimeGenerationDto,
    )
    def get_exact(runtime_generation_fingerprint: ShaPath) -> ExactRuntimeGenerationDto:
        try:
            manifest = reader.require_runtime_generation(runtime_generation_fingerprint)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="RUNTIME_GENERATION_NOT_FOUND") from exc
        actual = getattr(manifest, "runtime_generation_fingerprint", None)
        if actual != runtime_generation_fingerprint:
            raise HTTPException(status_code=500, detail="RUNTIME_GENERATION_IDENTITY_MISMATCH")
        return ExactRuntimeGenerationDto(runtime_generation_fingerprint=actual)

    return router


__all__ = [name for name in globals() if name.startswith(("Active", "Exact", "Only", "RUNTIME", "create_"))]
