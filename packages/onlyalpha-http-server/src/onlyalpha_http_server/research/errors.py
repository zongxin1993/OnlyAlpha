"""Stable HTTP translation for Research Query failures."""

from __future__ import annotations

from onlyalpha.research.query import OnlyResearchQueryError, OnlyResearchQueryErrorCode

from .schema import ResearchErrorDto

_STATUS = {
    OnlyResearchQueryErrorCode.INVALID_QUERY: 400,
    OnlyResearchQueryErrorCode.INVALID_TIME_RANGE: 400,
    OnlyResearchQueryErrorCode.INVALID_PAGE_LIMIT: 400,
    OnlyResearchQueryErrorCode.RESEARCH_ARTIFACT_NOT_FOUND: 404,
    OnlyResearchQueryErrorCode.STATISTICS_NOT_FOUND: 404,
    OnlyResearchQueryErrorCode.CANDIDATE_NOT_FOUND: 404,
    OnlyResearchQueryErrorCode.SERIES_NOT_FOUND: 404,
    OnlyResearchQueryErrorCode.SCIENTIFIC_EVIDENCE_NOT_AVAILABLE: 409,
    OnlyResearchQueryErrorCode.RESEARCH_ARTIFACT_CORRUPT: 500,
}


def research_error_response(error: OnlyResearchQueryError) -> tuple[int, ResearchErrorDto]:
    return _STATUS[error.code], ResearchErrorDto(code=error.code.value, detail=error.detail)
