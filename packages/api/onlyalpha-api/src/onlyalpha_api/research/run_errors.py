"""Stable HTTP translation for Research Run command/query failures."""

from __future__ import annotations

from onlyalpha.research.command.errors import OnlyResearchCommandError
from onlyalpha.research.run.errors import (
    OnlyPostgresSchemaIncompatibleError,
    OnlyResearchRunAdmissionError,
    OnlyResearchRunIntegrityError,
    OnlyResearchRunNotFoundError,
    OnlyResearchRunStoreUnavailableError,
)
from onlyalpha.research.specification.errors import OnlyResearchSpecificationError

from .run_schema import ResearchRunErrorDto, ResearchRunErrorEnvelopeDto


def run_error_response(error: Exception) -> tuple[int, ResearchRunErrorEnvelopeDto]:
    if isinstance(error, OnlyResearchCommandError):
        status = 409 if error.code.endswith(("_CONFLICT", "_CONCURRENT_CHANGE")) else 400
        return status, _body(error.phase.value, error.code, error.detail)
    if isinstance(error, OnlyResearchSpecificationError):
        return 400, _body(error.phase.value, error.code, error.detail)
    if isinstance(error, OnlyResearchRunAdmissionError):
        status = (
            404
            if error.code == "RESEARCH_DATASET_NOT_FOUND"
            else 500
            if error.code == "RESEARCH_DATASET_CORRUPT"
            else 400
        )
        return status, _body(error.phase, error.code, error.detail)
    if isinstance(error, OnlyResearchRunNotFoundError):
        return 404, _body("QUERY", error.code, "Research Run was not found")
    if isinstance(error, OnlyResearchRunStoreUnavailableError):
        return 503, _body("PERSISTENCE", error.code, "Research Run Store is unavailable")
    if isinstance(error, OnlyPostgresSchemaIncompatibleError):
        return 500, _body("PERSISTENCE", error.code, "PostgreSQL schema is incompatible")
    if isinstance(error, OnlyResearchRunIntegrityError):
        return 500, _body("PERSISTENCE", error.code, "Research Run authority failed verification")
    return 500, _body("OPERATIONAL", "RESEARCH_COMMAND_INTERNAL_ERROR", "Research command failed")


def _body(phase: str, code: str, detail: str) -> ResearchRunErrorEnvelopeDto:
    return ResearchRunErrorEnvelopeDto(error=ResearchRunErrorDto(phase=phase, code=code, detail=detail))


__all__ = ["run_error_response"]
