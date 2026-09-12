"""Exact read-only Product projection over Research Statistics Authority."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Annotated, Protocol, cast

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, ConfigDict

from onlyalpha.research.evaluation.errors import OnlyResearchStatisticsResultStoreError

EXACT_STATISTICS_ROUTE_TAG = "exact-research-statistics"


class OnlyExactResearchStatisticsReader(Protocol):
    def load_verified(self, statistics_fingerprint: str) -> object: ...


class ExactResearchStatisticsDto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: int = 1
    statistics_result_fingerprint: str
    payload: dict[str, object]


ShaPath = Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")]


def create_exact_statistics_router(reader: OnlyExactResearchStatisticsReader) -> APIRouter:
    router = APIRouter(prefix="/api/v2/research/statistics", tags=[EXACT_STATISTICS_ROUTE_TAG])

    @router.get(
        "/{statistics_result_fingerprint}",
        operation_id="get_exact_research_statistics_v2",
        response_model=ExactResearchStatisticsDto,
    )
    def get_statistics(statistics_result_fingerprint: ShaPath) -> ExactResearchStatisticsDto:
        try:
            value = reader.load_verified(statistics_result_fingerprint)
            manifest = _required_attr(value, "manifest")
            if _required_attr(manifest, "statistics_result_fingerprint") != statistics_result_fingerprint:
                raise ValueError("RESEARCH_STATISTICS_IDENTITY_MISMATCH")
            payload: dict[str, object] = {"manifest": _to_dict(manifest)}
            summary = getattr(value, "summary", None)
            if summary is not None:
                payload["summary"] = _to_dict(summary)
            else:
                rows = _required_attr(value, "rows")
                payload["rows"] = [_to_dict(row) for row in cast(Iterable[object], rows)]
        except OnlyResearchStatisticsResultStoreError as error:
            if error.code.endswith("_NOT_FOUND"):
                raise HTTPException(status_code=404, detail="RESEARCH_STATISTICS_NOT_FOUND") from error
            raise HTTPException(status_code=500, detail="RESEARCH_STATISTICS_CORRUPT") from error
        except Exception as error:
            raise HTTPException(status_code=500, detail="RESEARCH_STATISTICS_CORRUPT") from error
        return ExactResearchStatisticsDto(
            statistics_result_fingerprint=statistics_result_fingerprint,
            payload=payload,
        )

    return router


def _to_dict(value: object) -> dict[str, object]:
    method = getattr(value, "to_dict", None)
    if not callable(method):
        raise TypeError("RESEARCH_STATISTICS_PROJECTION_INVALID")
    payload = method()
    if not isinstance(payload, Mapping) or any(not isinstance(key, str) for key in payload):
        raise TypeError("RESEARCH_STATISTICS_PROJECTION_INVALID")
    return dict(cast(Mapping[str, object], payload))


def _required_attr(value: object, name: str) -> object:
    result = getattr(value, name)
    if result is None:
        raise TypeError("RESEARCH_STATISTICS_PROJECTION_INVALID")
    return result


__all__ = [name for name in globals() if name.startswith(("EXACT", "Exact", "Only", "create_"))]
