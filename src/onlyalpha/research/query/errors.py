"""Stable fail-closed errors for the Research Query boundary."""

from __future__ import annotations

from enum import StrEnum


class OnlyResearchQueryErrorCode(StrEnum):
    INVALID_QUERY = "INVALID_QUERY"
    INVALID_TIME_RANGE = "INVALID_TIME_RANGE"
    INVALID_PAGE_LIMIT = "INVALID_PAGE_LIMIT"
    RESEARCH_ARTIFACT_NOT_FOUND = "RESEARCH_ARTIFACT_NOT_FOUND"
    RESEARCH_ARTIFACT_CORRUPT = "RESEARCH_ARTIFACT_CORRUPT"
    STATISTICS_NOT_FOUND = "STATISTICS_NOT_FOUND"
    SCIENTIFIC_EVIDENCE_NOT_AVAILABLE = "SCIENTIFIC_EVIDENCE_NOT_AVAILABLE"
    CANDIDATE_NOT_FOUND = "CANDIDATE_NOT_FOUND"
    SERIES_NOT_FOUND = "SERIES_NOT_FOUND"


class OnlyResearchQueryError(RuntimeError):
    def __init__(self, code: OnlyResearchQueryErrorCode, detail: str) -> None:
        if not isinstance(code, OnlyResearchQueryErrorCode) or not detail:
            raise ValueError("Research Query error contract is invalid")
        self.code = code
        self.detail = detail
        super().__init__(f"{code.value}: {detail}")
