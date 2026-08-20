"""Thin application boundary from Definition transport to the Domain resolver."""

from __future__ import annotations

from onlyalpha.research.definition.errors import OnlyResearchDefinitionError, OnlyResearchDefinitionPhase
from onlyalpha.research.definition.resolver import OnlyResearchDefinitionResolver

from .definition_schema import ResearchDefinitionRequestDto, ResearchDefinitionResolutionDto


class ResearchDefinitionApiService:
    def __init__(self, resolver: OnlyResearchDefinitionResolver) -> None:
        self._resolver = resolver

    def resolve(self, request: ResearchDefinitionRequestDto) -> ResearchDefinitionResolutionDto:
        try:
            definition = request.to_domain()
        except (KeyError, TypeError, ValueError) as exc:
            raise OnlyResearchDefinitionError(
                OnlyResearchDefinitionPhase.SCHEMA,
                "RESEARCH_DEFINITION_REQUEST_INVALID",
                "$",
                str(exc),
            ) from exc
        return ResearchDefinitionResolutionDto.from_model(self._resolver.resolve(definition))


__all__ = ["ResearchDefinitionApiService"]
