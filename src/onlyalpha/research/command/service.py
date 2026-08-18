"""Idempotent submission and cancellation application service."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from onlyalpha.research.run.admission import OnlyResearchRunAdmissionService
from onlyalpha.research.run.errors import OnlyResearchRunRevisionConflictError
from onlyalpha.research.run.model import OnlyResearchRun, OnlyResearchRunId, OnlyResearchRunState
from onlyalpha.research.specification.model import OnlyResearchSpecification

from .errors import (
    OnlyResearchCancellationConflictError,
    OnlyResearchCommandConcurrencyError,
    OnlyResearchSubmissionConflictError,
)
from .model import (
    OnlyResearchSubmissionKey,
    OnlyResearchSubmitCommand,
    OnlyResearchSubmitDisposition,
    OnlyResearchSubmitOutcome,
)
from .store import OnlyResearchCommandStore


class OnlyResearchCommandService:
    def __init__(
        self,
        *,
        admission: OnlyResearchRunAdmissionService,
        store: OnlyResearchCommandStore,
        now_utc: Callable[[], datetime],
        cancellation_cas_attempts: int = 3,
    ) -> None:
        if cancellation_cas_attempts < 1:
            raise ValueError("cancellation_cas_attempts must be positive")
        self._admission = admission
        self._store = store
        self._now_utc = now_utc
        self._cancellation_cas_attempts = cancellation_cas_attempts

    def submit_research_run(
        self, submission_key: OnlyResearchSubmissionKey, specification: OnlyResearchSpecification
    ) -> OnlyResearchSubmitOutcome:
        strict = OnlyResearchSpecification.from_dict(specification.to_dict())
        command = OnlyResearchSubmitCommand(submission_key, strict)
        existing = self._store.find_submission(submission_key)
        if existing is not None:
            return self._replay(command, existing.command_fingerprint, existing.run_id)
        prepared = self._admission.prepare(strict)
        record = self._store.create_queued_submission(prepared, submission_key, command.command_fingerprint)
        if record.command_fingerprint != command.command_fingerprint:
            raise OnlyResearchSubmissionConflictError()
        disposition = (
            OnlyResearchSubmitDisposition.CREATED
            if record.run_id == prepared.run_id
            else OnlyResearchSubmitDisposition.REUSED
        )
        return OnlyResearchSubmitOutcome(disposition, self._store.load(record.run_id))

    def request_research_run_cancellation(self, run_id: OnlyResearchRunId) -> OnlyResearchRun:
        for _ in range(self._cancellation_cas_attempts):
            current = self._store.load(run_id)
            if current.state in {OnlyResearchRunState.CANCEL_REQUESTED, OnlyResearchRunState.CANCELLED}:
                return current
            if current.state in {OnlyResearchRunState.COMPLETED, OnlyResearchRunState.FAILED}:
                raise OnlyResearchCancellationConflictError()
            target = (
                OnlyResearchRunState.CANCELLED
                if current.state is OnlyResearchRunState.QUEUED
                else OnlyResearchRunState.CANCEL_REQUESTED
            )
            transitioned = current.transition(target, at=self._now_utc())
            try:
                return self._store.commit_transition(current, transitioned)
            except OnlyResearchRunRevisionConflictError:
                continue
        raise OnlyResearchCommandConcurrencyError()

    def _replay(
        self, command: OnlyResearchSubmitCommand, existing_fingerprint: str, run_id: OnlyResearchRunId
    ) -> OnlyResearchSubmitOutcome:
        if existing_fingerprint != command.command_fingerprint:
            raise OnlyResearchSubmissionConflictError()
        return OnlyResearchSubmitOutcome(
            OnlyResearchSubmitDisposition.REUSED,
            self._store.load(run_id),
        )


__all__ = ["OnlyResearchCommandService"]
