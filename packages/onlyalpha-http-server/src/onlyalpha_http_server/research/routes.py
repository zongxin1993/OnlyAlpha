"""Thin GET-only adapter over the Research Query service."""

from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import APIRouter, Query

from onlyalpha.research.query import (
    DEFAULT_PAGE_SIZE,
    OnlyResearchQueryService,
    OnlyResearchScientificSeriesQuery,
    OnlyResearchStatisticSeriesQuery,
)

from .schema import (
    ResearchArtifactSummaryDto,
    ResearchCandidateCatalogDto,
    ResearchCandidateGraphDto,
    ResearchErrorDto,
    ResearchPublishedSeriesCatalogDto,
    ResearchScientificSeriesPageDto,
    ResearchStatisticsCatalogDto,
    ResearchStatisticSeriesPageDto,
)

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ResearchErrorDto, "description": "Invalid Research query"},
    404: {"model": ResearchErrorDto, "description": "Exact Artifact or Statistics identity not found"},
    409: {"model": ResearchErrorDto, "description": "Scientific evidence is unavailable for this profile"},
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


ARTIFACT_ROUTE_TAG = "research-artifacts"


def create_artifact_router(service: OnlyResearchQueryService) -> APIRouter:
    router = APIRouter(prefix="/api/v2/research/artifacts", tags=[ARTIFACT_ROUTE_TAG])

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
        "/{research_result_fingerprint}/candidates",
        response_model=ResearchCandidateCatalogDto,
        responses=_ERROR_RESPONSES,
    )
    def candidate_catalog(research_result_fingerprint: str) -> ResearchCandidateCatalogDto:
        return ResearchCandidateCatalogDto.from_model(service.list_candidates(research_result_fingerprint))

    @router.get(
        "/{research_result_fingerprint}/variables",
        response_model=ResearchPublishedSeriesCatalogDto,
        responses=_ERROR_RESPONSES,
    )
    def variable_catalog(research_result_fingerprint: str) -> ResearchPublishedSeriesCatalogDto:
        return ResearchPublishedSeriesCatalogDto.from_model(service.list_published_series(research_result_fingerprint))

    @router.get(
        "/{research_result_fingerprint}/market/series",
        response_model=ResearchScientificSeriesPageDto,
        responses=_ERROR_RESPONSES,
    )
    def market_series(
        research_result_fingerprint: str,
        instrument_id: str,
        from_ts_event_ns: CanonicalIntegerQuery = None,
        to_ts_event_ns: CanonicalIntegerQuery = None,
        after_ts_event_ns: CanonicalIntegerQuery = None,
        limit: int = Query(default=DEFAULT_PAGE_SIZE),
    ) -> ResearchScientificSeriesPageDto:
        query = OnlyResearchScientificSeriesQuery(
            research_result_fingerprint,
            instrument_id=instrument_id,
            from_ts_event_ns=_optional_integer(from_ts_event_ns),
            to_ts_event_ns=_optional_integer(to_ts_event_ns),
            after_ts_event_ns=_optional_integer(after_ts_event_ns),
            limit=limit,
        )
        return ResearchScientificSeriesPageDto.from_model(service.get_market_series(query))

    @router.get(
        "/{research_result_fingerprint}/variables/{calculation_fingerprint}/{node_fingerprint}/{output_name}/series",
        response_model=ResearchScientificSeriesPageDto,
        responses=_ERROR_RESPONSES,
    )
    def variable_series(
        research_result_fingerprint: str,
        calculation_fingerprint: str,
        node_fingerprint: str,
        output_name: str,
        instrument_id: str,
        candidate_fingerprint: str | None = None,
        from_ts_event_ns: CanonicalIntegerQuery = None,
        to_ts_event_ns: CanonicalIntegerQuery = None,
        after_ts_event_ns: CanonicalIntegerQuery = None,
        limit: int = Query(default=DEFAULT_PAGE_SIZE),
    ) -> ResearchScientificSeriesPageDto:
        query = OnlyResearchScientificSeriesQuery(
            research_result_fingerprint,
            instrument_id=instrument_id,
            candidate_fingerprint=candidate_fingerprint,
            calculation_fingerprint=calculation_fingerprint,
            node_fingerprint=node_fingerprint,
            output_name=output_name,
            from_ts_event_ns=_optional_integer(from_ts_event_ns),
            to_ts_event_ns=_optional_integer(to_ts_event_ns),
            after_ts_event_ns=_optional_integer(after_ts_event_ns),
            limit=limit,
        )
        return ResearchScientificSeriesPageDto.from_model(service.get_variable_series(query))

    @router.get(
        "/{research_result_fingerprint}/signals/{candidate_fingerprint}/{role}/series",
        response_model=ResearchScientificSeriesPageDto,
        responses=_ERROR_RESPONSES,
    )
    def signal_series(
        research_result_fingerprint: str,
        candidate_fingerprint: str,
        role: str,
        instrument_id: str,
        from_ts_event_ns: CanonicalIntegerQuery = None,
        to_ts_event_ns: CanonicalIntegerQuery = None,
        after_ts_event_ns: CanonicalIntegerQuery = None,
        limit: int = Query(default=DEFAULT_PAGE_SIZE),
    ) -> ResearchScientificSeriesPageDto:
        query = OnlyResearchScientificSeriesQuery(
            research_result_fingerprint,
            instrument_id=instrument_id,
            candidate_fingerprint=candidate_fingerprint,
            role=role,
            from_ts_event_ns=_optional_integer(from_ts_event_ns),
            to_ts_event_ns=_optional_integer(to_ts_event_ns),
            after_ts_event_ns=_optional_integer(after_ts_event_ns),
            limit=limit,
        )
        return ResearchScientificSeriesPageDto.from_model(service.get_signal_series(query))

    @router.get(
        "/{research_result_fingerprint}/candidates/{candidate_fingerprint}/graph",
        response_model=ResearchCandidateGraphDto,
        responses=_ERROR_RESPONSES,
    )
    def candidate_graph(research_result_fingerprint: str, candidate_fingerprint: str) -> ResearchCandidateGraphDto:
        return ResearchCandidateGraphDto.from_model(
            service.get_candidate_graph(research_result_fingerprint, candidate_fingerprint)
        )

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


__all__ = ["ARTIFACT_ROUTE_TAG", "create_artifact_router"]
