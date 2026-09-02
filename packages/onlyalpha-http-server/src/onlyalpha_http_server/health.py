"""Stable liveness/readiness HTTP contract for the full Research API."""

from __future__ import annotations

from typing import Protocol

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from onlyalpha.research.operations.readiness import OnlyResearchReadiness, OnlyResearchReadinessStatus


class _ReadinessProbe(Protocol):
    def inspect(self) -> OnlyResearchReadiness: ...


class OnlyProductExecutionCapacityProbe(Protocol):
    def has_fresh_worker(self) -> bool: ...


class _KernelStateProjection(Protocol):
    @property
    def value(self) -> str: ...


class _KernelStatusProjection(Protocol):
    @property
    def state(self) -> _KernelStateProjection: ...

    @property
    def ready(self) -> bool: ...


class _KernelStatusReader(Protocol):
    @property
    def status(self) -> _KernelStatusProjection: ...


class OnlyKernelResearchReadinessProjection:
    """Preserve the Research health DTO while projecting Product Kernel readiness."""

    def __init__(self, kernel: _KernelStatusReader, verification: OnlyResearchReadiness | None) -> None:
        self._kernel = kernel
        self._verification = verification

    def inspect(self) -> OnlyResearchReadiness:
        status = self._kernel.status
        from onlyalpha.research.operations.readiness import OnlyResearchReadinessCheck

        verification = self._verification
        if status.ready and verification is not None and verification.status is OnlyResearchReadinessStatus.READY:
            return verification
        if verification is not None and verification.status is OnlyResearchReadinessStatus.NOT_READY:
            return verification
        return OnlyResearchReadiness(
            OnlyResearchReadinessStatus.NOT_READY,
            (
                *(verification.checks if verification is not None else ()),
                OnlyResearchReadinessCheck("product_kernel", status.state.value),
            ),
            f"KERNEL_{status.state.value}",
        )


class ResearchHealthDto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    status: str
    checks: dict[str, str]
    reason: str | None = None


class ProductExecutionHealthDto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    status: str
    checks: dict[str, str]
    reason: str | None = None


class _UnavailableProbe:
    def inspect(self) -> OnlyResearchReadiness:
        from onlyalpha.research.operations.readiness import OnlyResearchReadinessCheck

        return OnlyResearchReadiness(
            OnlyResearchReadinessStatus.NOT_READY,
            (OnlyResearchReadinessCheck("composition", "UNAVAILABLE"),),
            "COMPOSITION_UNAVAILABLE",
        )


def create_health_router(
    probe: _ReadinessProbe | None,
    execution_capacity: OnlyProductExecutionCapacityProbe | None = None,
) -> APIRouter:
    router = APIRouter(tags=["health"])
    readiness = probe or _UnavailableProbe()

    @router.get("/health/live", response_model=ResearchHealthDto)
    def live() -> ResearchHealthDto:
        return ResearchHealthDto(status="LIVE", checks={"http": "LIVE"})

    @router.get(
        "/health/ready",
        response_model=ResearchHealthDto,
        responses={503: {"model": ResearchHealthDto}},
    )
    def ready() -> ResearchHealthDto | JSONResponse:
        inspected = readiness.inspect()
        body = ResearchHealthDto(
            status=inspected.status.value,
            checks={item.name: item.status for item in inspected.checks},
            reason=inspected.reason,
        )
        if inspected.status is OnlyResearchReadinessStatus.READY:
            return body
        return JSONResponse(status_code=503, content=body.model_dump(mode="json"))

    @router.get(
        "/health/execution",
        response_model=ProductExecutionHealthDto,
        responses={503: {"model": ProductExecutionHealthDto}},
    )
    def execution() -> ProductExecutionHealthDto | JSONResponse:
        if execution_capacity is None:
            body = ProductExecutionHealthDto(
                status="UNKNOWN",
                checks={"backtest_worker": "UNKNOWN"},
                reason="BACKTEST_WORKER_CAPACITY_UNAVAILABLE",
            )
            return JSONResponse(status_code=503, content=body.model_dump(mode="json"))
        try:
            available = execution_capacity.has_fresh_worker()
        except Exception:
            available = False
        body = ProductExecutionHealthDto(
            status="AVAILABLE" if available else "DEGRADED",
            checks={"backtest_worker": "AVAILABLE" if available else "ABSENT"},
            reason=None if available else "BACKTEST_WORKER_ABSENT",
        )
        if available:
            return body
        return JSONResponse(status_code=503, content=body.model_dump(mode="json"))

    return router


__all__ = [
    "OnlyKernelResearchReadinessProjection",
    "OnlyProductExecutionCapacityProbe",
    "ProductExecutionHealthDto",
    "ResearchHealthDto",
    "create_health_router",
]
