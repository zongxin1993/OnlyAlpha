"""Strict HTTP DTOs for Research Run commands and operational reads."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue, model_validator

from onlyalpha.research.command.model import OnlyResearchRunPage, OnlyResearchSubmitOutcome
from onlyalpha.research.provenance import OnlyResearchAuthoringProvenance
from onlyalpha.research.run.model import OnlyResearchRun, OnlyResearchRunFailure

from .schema import RESEARCH_API_SCHEMA_VERSION


class _RunDto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


def _time(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class ResearchAuthoringProvenanceDto(_RunDto):
    schema_version: Literal[1]
    experiment_id: str
    source_repository: str
    source_revision: str
    source_tree: str
    candidate_provider_id: str
    candidate_provider_version: str
    candidate_provider_content_fingerprint: str
    catalog_generation_fingerprint: str
    execution_generation_fingerprint: str
    source_locator: str | None = None

    @model_validator(mode="after")
    def _validate_domain_contract(self) -> ResearchAuthoringProvenanceDto:
        self.to_model()
        return self

    def to_model(self) -> OnlyResearchAuthoringProvenance:
        return OnlyResearchAuthoringProvenance.from_dict(self.model_dump(exclude_none=True))

    @classmethod
    def from_model(cls, value: OnlyResearchAuthoringProvenance | None) -> ResearchAuthoringProvenanceDto | None:
        return None if value is None else cls.model_validate(value.to_dict())


class SubmitResearchRunRequest(_RunDto):
    specification: dict[str, JsonValue]
    authoring_provenance: ResearchAuthoringProvenanceDto | None = None


class ResearchRunFailureDto(_RunDto):
    phase: str
    code: str
    detail: str

    @classmethod
    def from_model(cls, value: OnlyResearchRunFailure | None) -> ResearchRunFailureDto | None:
        return None if value is None else cls(phase=value.phase.value, code=value.code, detail=value.detail)


class ResearchRunDto(_RunDto):
    schema_version: Literal[2] = RESEARCH_API_SCHEMA_VERSION
    run_id: str
    revision: str
    state: str
    specification_schema_version: int
    specification_fingerprint: str
    admission_resolution_fingerprint: str
    specification: dict[str, JsonValue]
    queued_at: str
    started_at: str | None
    cancel_requested_at: str | None
    finished_at: str | None
    result_ref: str | None
    artifact_ref: str | None
    failure: ResearchRunFailureDto | None

    @classmethod
    def from_model(cls, value: OnlyResearchRun) -> ResearchRunDto:
        return cls(
            run_id=value.run_id.value,
            revision=str(value.revision),
            state=value.state.value,
            specification_schema_version=value.specification.schema_version,
            specification_fingerprint=value.specification_fingerprint,
            admission_resolution_fingerprint=value.admission_resolution_fingerprint,
            specification=dict(value.specification.to_dict()),  # type: ignore[arg-type]
            queued_at=_time(value.queued_at) or "",
            started_at=_time(value.started_at),
            cancel_requested_at=_time(value.cancel_requested_at),
            finished_at=_time(value.finished_at),
            result_ref=value.research_result_fingerprint,
            artifact_ref=value.artifact_content_fingerprint,
            failure=ResearchRunFailureDto.from_model(value.failure),
        )


class ResearchRunSummaryDto(_RunDto):
    schema_version: Literal[2] = RESEARCH_API_SCHEMA_VERSION
    run_id: str
    revision: str
    state: str
    specification_schema_version: int
    specification_fingerprint: str
    admission_resolution_fingerprint: str
    queued_at: str
    started_at: str | None
    cancel_requested_at: str | None
    finished_at: str | None
    result_ref: str | None
    artifact_ref: str | None
    failure: ResearchRunFailureDto | None

    @classmethod
    def from_model(cls, value: OnlyResearchRun) -> ResearchRunSummaryDto:
        full = ResearchRunDto.from_model(value)
        return cls(**full.model_dump(exclude={"specification"}))


class ResearchRunExecutionEvidenceDto(_RunDto):
    schema_version: Literal[1] = 1
    run_id: str
    revision: str
    result_ref: str | None
    calculation_execution_evidence_refs: tuple[str, ...]
    authoring_provenance: ResearchAuthoringProvenanceDto | None

    @classmethod
    def from_model(cls, value: OnlyResearchRun) -> ResearchRunExecutionEvidenceDto:
        return cls(
            run_id=value.run_id.value,
            revision=str(value.revision),
            result_ref=value.research_result_fingerprint,
            calculation_execution_evidence_refs=value.calculation_execution_evidence_fingerprints,
            authoring_provenance=ResearchAuthoringProvenanceDto.from_model(value.authoring_provenance),
        )


class SubmitResearchRunResponse(_RunDto):
    submission_disposition: str
    run: ResearchRunDto

    @classmethod
    def from_model(cls, value: OnlyResearchSubmitOutcome) -> SubmitResearchRunResponse:
        return cls(
            submission_disposition=value.disposition.value,
            run=ResearchRunDto.from_model(value.run),
        )


class ResearchRunPageDto(_RunDto):
    schema_version: Literal[2] = RESEARCH_API_SCHEMA_VERSION
    runs: tuple[ResearchRunSummaryDto, ...]
    has_more: bool
    next_cursor: str | None

    @classmethod
    def from_model(cls, value: OnlyResearchRunPage) -> ResearchRunPageDto:
        return cls(
            runs=tuple(ResearchRunSummaryDto.from_model(item) for item in value.runs),
            has_more=value.has_more,
            next_cursor=value.next_cursor,
        )


class ResearchRunErrorDto(_RunDto):
    phase: str
    code: str
    detail: str


class ResearchRunErrorEnvelopeDto(_RunDto):
    error: ResearchRunErrorDto


__all__ = [name for name in globals() if name.startswith(("Research", "Submit"))]
