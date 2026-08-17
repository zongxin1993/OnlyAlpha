"""Stable Research Run operational errors."""

from __future__ import annotations


class OnlyResearchRunError(RuntimeError):
    code = "RESEARCH_RUN_ERROR"


class OnlyResearchRunAdmissionError(OnlyResearchRunError):
    code = "RESEARCH_RUN_ADMISSION_FAILED"


class OnlyResearchRunNotFoundError(OnlyResearchRunError):
    code = "RESEARCH_RUN_NOT_FOUND"


class OnlyResearchRunStateConflictError(OnlyResearchRunError):
    code = "RESEARCH_RUN_STATE_CONFLICT"


class OnlyResearchRunRevisionConflictError(OnlyResearchRunError):
    code = "RESEARCH_RUN_REVISION_CONFLICT"


class OnlyResearchRunIntegrityError(OnlyResearchRunError):
    code = "RESEARCH_RUN_INTEGRITY_ERROR"


class OnlyResearchRunStoreUnavailableError(OnlyResearchRunError):
    code = "RESEARCH_RUN_STORE_UNAVAILABLE"


class OnlyPostgresSchemaIncompatibleError(OnlyResearchRunError):
    code = "POSTGRES_SCHEMA_INCOMPATIBLE"


class OnlyPostgresMigrationIntegrityError(OnlyResearchRunError):
    code = "POSTGRES_MIGRATION_INTEGRITY_ERROR"


__all__ = [name for name in globals() if name.startswith("Only")]
