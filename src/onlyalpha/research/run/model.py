"""Immutable Research Run operational authority and transition rules."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.specification.model import OnlyResearchSpecification

from .errors import OnlyResearchRunIntegrityError, OnlyResearchRunStateConflictError

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, order=True, slots=True)
class OnlyResearchRunId:
    value: str

    def __post_init__(self) -> None:
        try:
            parsed = uuid.UUID(self.value)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("Research Run ID must be a canonical UUID") from exc
        if parsed.version != 4 or str(parsed) != self.value:
            raise ValueError("Research Run ID must be a canonical UUID4")

    @classmethod
    def new(cls) -> OnlyResearchRunId:
        return cls(str(uuid.uuid4()))

    def __str__(self) -> str:
        return self.value


class OnlyResearchRunState(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def terminal(self) -> bool:
        return self in {self.COMPLETED, self.FAILED, self.CANCELLED}


class OnlyResearchRunFailurePhase(StrEnum):
    ADMISSION = "ADMISSION"
    EXECUTION = "EXECUTION"
    RESULT_COMMIT = "RESULT_COMMIT"
    ARTIFACT_COMMIT = "ARTIFACT_COMMIT"
    OPERATIONAL = "OPERATIONAL"


@dataclass(frozen=True, slots=True)
class OnlyResearchRunFailure:
    phase: OnlyResearchRunFailurePhase
    code: str
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.phase, OnlyResearchRunFailurePhase):
            raise ValueError("Research Run failure phase is invalid")
        if not self.code or not self.code.replace("_", "").isalnum() or self.code != self.code.upper():
            raise ValueError("Research Run failure code must be stable upper snake case")
        if not self.detail:
            raise ValueError("Research Run failure detail is required")


_TRANSITIONS: dict[OnlyResearchRunState, frozenset[OnlyResearchRunState]] = {
    OnlyResearchRunState.QUEUED: frozenset({OnlyResearchRunState.RUNNING, OnlyResearchRunState.CANCELLED}),
    OnlyResearchRunState.RUNNING: frozenset(
        {
            OnlyResearchRunState.COMPLETED,
            OnlyResearchRunState.FAILED,
            OnlyResearchRunState.CANCEL_REQUESTED,
        }
    ),
    OnlyResearchRunState.CANCEL_REQUESTED: frozenset(
        {OnlyResearchRunState.CANCELLED, OnlyResearchRunState.COMPLETED, OnlyResearchRunState.FAILED}
    ),
    OnlyResearchRunState.COMPLETED: frozenset(),
    OnlyResearchRunState.FAILED: frozenset(),
    OnlyResearchRunState.CANCELLED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class OnlyResearchRun:
    run_id: OnlyResearchRunId
    revision: int
    state: OnlyResearchRunState
    specification: OnlyResearchSpecification
    specification_fingerprint: str
    canonical_specification_payload: str
    admission_resolution_fingerprint: str
    queued_at: datetime
    started_at: datetime | None = None
    cancel_requested_at: datetime | None = None
    finished_at: datetime | None = None
    research_result_fingerprint: str | None = None
    artifact_content_fingerprint: str | None = None
    failure: OnlyResearchRunFailure | None = None
    calculation_execution_evidence_fingerprints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        try:
            if not isinstance(self.run_id, OnlyResearchRunId):
                raise ValueError("Run ID is invalid")
            if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 0:
                raise ValueError("revision must be a non-negative integer")
            if not isinstance(self.state, OnlyResearchRunState):
                raise ValueError("state is invalid")
            if not isinstance(self.specification, OnlyResearchSpecification):
                raise ValueError("Specification is invalid")
            _sha(self.specification_fingerprint, "specification_fingerprint")
            _sha(self.admission_resolution_fingerprint, "admission_resolution_fingerprint")
            if self.specification.specification_fingerprint != self.specification_fingerprint:
                raise ValueError("Specification fingerprint linkage mismatch")
            if self.canonical_specification_payload != only_canonical_json(self.specification.to_dict()):
                raise ValueError("Specification payload is not exact canonical JSON")
            for name in ("research_result_fingerprint", "artifact_content_fingerprint"):
                value = getattr(self, name)
                if value is not None:
                    _sha(value, name)
            evidence = tuple(sorted(self.calculation_execution_evidence_fingerprints))
            if evidence != self.calculation_execution_evidence_fingerprints or len(evidence) != len(set(evidence)):
                raise ValueError("Calculation Execution Evidence references must be canonical and unique")
            for value in evidence:
                _sha(value, "calculation_execution_evidence_fingerprint")
            if evidence and self.research_result_fingerprint is None:
                raise ValueError("Execution Evidence references require Research Result reference")
            for name in ("queued_at", "started_at", "cancel_requested_at", "finished_at"):
                value = getattr(self, name)
                if value is not None:
                    _utc(value, name)
            if self.started_at is not None and self.started_at < self.queued_at:
                raise ValueError("started_at precedes queued_at")
            if self.cancel_requested_at is not None:
                if self.started_at is None:
                    raise ValueError("cancel_requested_at requires started_at")
                if self.cancel_requested_at < self.started_at:
                    raise ValueError("cancel_requested_at precedes started_at")
            if self.finished_at is not None and self.finished_at < self.queued_at:
                raise ValueError("finished_at precedes queued_at")
            if self.finished_at is not None and self.started_at is not None and self.finished_at < self.started_at:
                raise ValueError("finished_at precedes started_at")
            if (
                self.finished_at is not None
                and self.cancel_requested_at is not None
                and self.finished_at < self.cancel_requested_at
            ):
                raise ValueError("finished_at precedes cancel_requested_at")
            if self.artifact_content_fingerprint is not None and self.research_result_fingerprint is None:
                raise ValueError("Artifact reference requires Research Result reference")
            if self.state is self.state.QUEUED and (
                any(
                    value is not None
                    for value in (
                        self.started_at,
                        self.cancel_requested_at,
                        self.finished_at,
                        self.research_result_fingerprint,
                        self.artifact_content_fingerprint,
                        self.failure,
                    )
                )
                or self.calculation_execution_evidence_fingerprints
            ):
                raise ValueError("QUEUED Run contains later lifecycle facts")
            if self.state in {self.state.RUNNING, self.state.CANCEL_REQUESTED} and evidence:
                raise ValueError("active Run cannot contain finalized Execution Evidence references")
            if self.state in {self.state.RUNNING, self.state.CANCEL_REQUESTED} and self.started_at is None:
                raise ValueError("active Run requires started_at")
            if self.state is self.state.RUNNING and self.cancel_requested_at is not None:
                raise ValueError("RUNNING cannot contain a cancellation request")
            if self.state is self.state.CANCEL_REQUESTED and self.cancel_requested_at is None:
                raise ValueError("CANCEL_REQUESTED requires cancel_requested_at")
            if self.state.terminal != (self.finished_at is not None):
                raise ValueError("terminal Run and finished_at must agree")
            if self.state is self.state.COMPLETED and (
                self.started_at is None
                or self.research_result_fingerprint is None
                or self.artifact_content_fingerprint is None
            ):
                raise ValueError("COMPLETED requires started execution and exact Result and Artifact references")
            if self.state is self.state.FAILED and (self.started_at is None or self.failure is None):
                raise ValueError("FAILED requires started execution and structured failure")
            if self.state is not self.state.FAILED and self.failure is not None:
                raise ValueError("failure is only valid for FAILED")
            if self.state is self.state.CANCELLED and ((self.started_at is None) != (self.cancel_requested_at is None)):
                raise ValueError("CANCELLED must be direct from QUEUED or follow a cancellation request")
        except ValueError as exc:
            raise OnlyResearchRunIntegrityError(str(exc)) from exc

    @classmethod
    def queued(
        cls,
        *,
        run_id: OnlyResearchRunId,
        specification: OnlyResearchSpecification,
        canonical_specification_payload: str,
        admission_resolution_fingerprint: str,
        queued_at: datetime,
    ) -> OnlyResearchRun:
        return cls(
            run_id,
            0,
            OnlyResearchRunState.QUEUED,
            specification,
            specification.specification_fingerprint,
            canonical_specification_payload,
            admission_resolution_fingerprint,
            queued_at,
        )

    def transition(
        self,
        target: OnlyResearchRunState,
        *,
        at: datetime,
        failure: OnlyResearchRunFailure | None = None,
        research_result_fingerprint: str | None = None,
        artifact_content_fingerprint: str | None = None,
        calculation_execution_evidence_fingerprints: tuple[str, ...] | None = None,
    ) -> OnlyResearchRun:
        _utc(at, "transition timestamp")
        if target not in _TRANSITIONS[self.state]:
            raise OnlyResearchRunStateConflictError(f"illegal Research Run transition: {self.state} -> {target}")
        started_at = self.started_at
        cancel_requested_at = self.cancel_requested_at
        finished_at = self.finished_at
        if target is target.RUNNING:
            started_at = at
        elif target is target.CANCEL_REQUESTED:
            cancel_requested_at = at
        else:
            finished_at = at
        if target is target.FAILED:
            next_failure = failure
        elif failure is not None:
            raise OnlyResearchRunStateConflictError("failure is only valid for FAILED transition")
        else:
            next_failure = None
        return OnlyResearchRun(
            run_id=self.run_id,
            revision=self.revision + 1,
            state=target,
            specification=self.specification,
            specification_fingerprint=self.specification_fingerprint,
            canonical_specification_payload=self.canonical_specification_payload,
            admission_resolution_fingerprint=self.admission_resolution_fingerprint,
            queued_at=self.queued_at,
            started_at=started_at,
            cancel_requested_at=cancel_requested_at,
            finished_at=finished_at,
            research_result_fingerprint=research_result_fingerprint or self.research_result_fingerprint,
            artifact_content_fingerprint=artifact_content_fingerprint or self.artifact_content_fingerprint,
            failure=next_failure,
            calculation_execution_evidence_fingerprints=(
                self.calculation_execution_evidence_fingerprints
                if calculation_execution_evidence_fingerprints is None
                else calculation_execution_evidence_fingerprints
            ),
        )

    def is_exact_successor_of(self, previous: OnlyResearchRun) -> bool:
        if self.run_id != previous.run_id or self.revision != previous.revision + 1:
            return False
        try:
            expected = previous.transition(
                self.state,
                at=self.started_at
                if self.state is self.state.RUNNING
                else self.cancel_requested_at
                if self.state is self.state.CANCEL_REQUESTED
                else self.finished_at,  # type: ignore[arg-type]
                failure=self.failure,
                research_result_fingerprint=self.research_result_fingerprint
                if self.research_result_fingerprint != previous.research_result_fingerprint
                else None,
                artifact_content_fingerprint=self.artifact_content_fingerprint
                if self.artifact_content_fingerprint != previous.artifact_content_fingerprint
                else None,
                calculation_execution_evidence_fingerprints=(
                    self.calculation_execution_evidence_fingerprints
                    if self.calculation_execution_evidence_fingerprints
                    != previous.calculation_execution_evidence_fingerprints
                    else None
                ),
            )
        except (OnlyResearchRunIntegrityError, OnlyResearchRunStateConflictError, ValueError):
            return False
        return expected == self


def _sha(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lower-case SHA256")
    return value


def _utc(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{name} must be timezone-aware UTC")
    return value


__all__ = [name for name in globals() if name.startswith("Only")]
