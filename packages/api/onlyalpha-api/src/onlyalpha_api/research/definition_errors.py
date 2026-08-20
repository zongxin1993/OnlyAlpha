"""Stable HTTP translation for Research Definition failures."""

from __future__ import annotations

from onlyalpha.research.definition import OnlyResearchDefinitionError

from .definition_schema import ResearchDefinitionErrorDto, ResearchDefinitionErrorEnvelopeDto


def definition_error_response(
    error: OnlyResearchDefinitionError,
) -> tuple[int, ResearchDefinitionErrorEnvelopeDto]:
    return 400, ResearchDefinitionErrorEnvelopeDto(
        error=ResearchDefinitionErrorDto(
            phase=error.phase.value,
            code=error.code,
            path=error.path,
            detail=error.detail,
        )
    )


__all__ = ["definition_error_response"]
