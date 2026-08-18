"""Thin GET-only adapter over the Research Query service."""

from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import APIRouter, Query

from onlyalpha.research.query import (
    DEFAULT_PAGE_SIZE,
    OnlyResearchQueryService,
    OnlyResearchStatisticSeriesQuery,
)

from .schema import (
    ResearchArtifactSummaryDto,
    ResearchErrorDto,
    ResearchStatisticsCatalogDto,
    ResearchStatisticSeriesPageDto,
)

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ResearchErrorDto, "description": "Invalid Research query"},
    404: {"model": ResearchErrorDto, "description": "Exact Artifact or Statistics identity not found"},
    500: {"model": ResearchErrorDto, "description": "Research Artifact verification failed"},
}

_CANONICAL_INTEGER = re.compile(r"^(?:0|-?[1-9][0-9]*)$")
CanonicalIntegerQuery = Annotated[str | None, Query(pattern=_CANONICAL_INTEGER.pattern)]


def _optional_integer(value: str | None) -> int | None:
    if value is None:
        return None
    if _CANONICAL_INTEGER.fullmatch(value) is None:
        raise ValueError("timestamp query must be a canonical decimal integer string")
    return int(value)


def create_artifact_router(service: OnlyResearchQueryService) -> APIRouter:
    router = APIRouter(prefix="/api/v2/research/artifacts", tags=["research"])

    @router.get(
        "/{research_result_fingerprint}",
        response_model=ResearchArtifactSummaryDto,
        responses=_ERROR_RESPONSES,
    )
    def artifact_summary(research_result_fingerprint: str) -> ResearchArtifactSummaryDto:
        return ResearchArtifactSummaryDto.from_model(service.get_artifact_summary(research_result_fingerprint))

    @router.get(
        "/{research_result_fingerprint}/statistics",
        response_model=ResearchStatisticsCatalogDto,
        responses=_ERROR_RESPONSES,
    )
    def statistics_catalog(research_result_fingerprint: str) -> ResearchStatisticsCatalogDto:
        return ResearchStatisticsCatalogDto.from_model(service.list_statistics(research_result_fingerprint))

    @router.get(
        "/{research_result_fingerprint}/statistics/{statistics_fingerprint}/series",
        response_model=ResearchStatisticSeriesPageDto,
        responses=_ERROR_RESPONSES,
    )
    def statistic_series(
        research_result_fingerprint: str,
        statistics_fingerprint: str,
        from_ts_event_ns: CanonicalIntegerQuery = None,
        to_ts_event_ns: CanonicalIntegerQuery = None,
        after_ts_event_ns: CanonicalIntegerQuery = None,
        limit: int = Query(default=DEFAULT_PAGE_SIZE),
    ) -> ResearchStatisticSeriesPageDto:
        query = OnlyResearchStatisticSeriesQuery(
            research_result_fingerprint,
            statistics_fingerprint,
            _optional_integer(from_ts_event_ns),
            _optional_integer(to_ts_event_ns),
            _optional_integer(after_ts_event_ns),
            limit,
        )
        return ResearchStatisticSeriesPageDto.from_model(service.get_statistic_series(query))

    return router
