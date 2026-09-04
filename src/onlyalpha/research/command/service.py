"""Idempotent submission and cancellation application service."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandId,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandOutcomeRef,
    OnlyProductCommandReceipt,
    only_cancel_research_run_command_fingerprint,
)
from onlyalpha.research.provenance import OnlyResearchAuthoringProvenance
from onlyalpha.research.run.admission import OnlyResearchRunAdmissionService
from onlyalpha.research.run.errors import (
    OnlyResearchRunIntegrityError,
    OnlyResearchRunNotFoundError,
    OnlyResearchRunRevisionConflictError,
)
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
        self,
        submission_key: OnlyResearchSubmissionKey,
        specification: OnlyResearchSpecification,
        provenance: OnlyResearchAuthoringProvenance | None = None,
    ) -> OnlyResearchSubmitOutcome:
        strict = OnlyResearchSpecification.from_dict(specification.to_dict())
        command = OnlyResearchSubmitCommand(submission_key, strict, provenance)
        existing = self._store.find_product_command_receipt(submission_key)
        if existing is not None:
            run = self._replay_receipt(
                existing,
                kind=OnlyProductCommandKind.CREATE_RESEARCH_RUN,
                fingerprint=command.command_fingerprint,
            )
            return OnlyResearchSubmitOutcome(OnlyResearchSubmitDisposition.REUSED, run)
        prepared = self._admission.prepare(strict, provenance=provenance)
        requested = OnlyProductCommandReceipt(
            command_id=submission_key,
            command_kind=OnlyProductCommandKind.CREATE_RESEARCH_RUN,
            command_fingerprint=command.command_fingerprint,
            outcome_ref=OnlyProductCommandOutcomeRef(
                OnlyProductCommandOutcomeKind.RESEARCH_RUN,
                prepared.run_id.value,
            ),
            accepted_at=prepared.queued_at,
        )
        record = self._store.create_queued_with_receipt(prepared, requested)
        run = self._replay_receipt(
            record,
            kind=OnlyProductCommandKind.CREATE_RESEARCH_RUN,
            fingerprint=command.command_fingerprint,
        )
        disposition = (
            OnlyResearchSubmitDisposition.CREATED
            if record.outcome_ref.outcome_id == prepared.run_id.value
            else OnlyResearchSubmitDisposition.REUSED
        )
        return OnlyResearchSubmitOutcome(disposition, run)

    def request_research_run_cancellation(
        self,
        run_id: OnlyResearchRunId,
        command_id: OnlyProductCommandId | None = None,
    ) -> OnlyResearchRun:
        if command_id is not None:
            fingerprint = only_cancel_research_run_command_fingerprint(run_id.value)
            existing = self._store.find_product_command_receipt(command_id)
            if existing is not None:
                return self._replay_receipt(
                    existing,
                    kind=OnlyProductCommandKind.CANCEL_RESEARCH_RUN,
                    fingerprint=fingerprint,
                    expected_run_id=run_id,
                )
            accepted_at = self._now_utc()
            receipt = OnlyProductCommandReceipt(
                command_id=command_id,
                command_kind=OnlyProductCommandKind.CANCEL_RESEARCH_RUN,
                command_fingerprint=fingerprint,
                outcome_ref=OnlyProductCommandOutcomeRef(
                    OnlyProductCommandOutcomeKind.RESEARCH_RUN,
                    run_id.value,
                ),
                accepted_at=accepted_at,
            )
            actual = self._store.request_cancellation_with_receipt(run_id, receipt)
            return self._replay_receipt(
                actual,
                kind=OnlyProductCommandKind.CANCEL_RESEARCH_RUN,
                fingerprint=fingerprint,
                expected_run_id=run_id,
            )
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

    def _replay_receipt(
        self,
        receipt: OnlyProductCommandReceipt,
        *,
        kind: OnlyProductCommandKind,
        fingerprint: str,
        expected_run_id: OnlyResearchRunId | None = None,
    ) -> OnlyResearchRun:
        if receipt.command_kind is not kind or receipt.command_fingerprint != fingerprint:
            raise OnlyResearchSubmissionConflictError()
        if receipt.outcome_ref.kind is not OnlyProductCommandOutcomeKind.RESEARCH_RUN:
            raise OnlyResearchRunIntegrityError("Product Command Receipt outcome kind is incompatible")
        run_id = OnlyResearchRunId(receipt.outcome_ref.outcome_id)
        if expected_run_id is not None and run_id != expected_run_id:
            raise OnlyResearchSubmissionConflictError()
        try:
            return self._store.load(run_id)
        except OnlyResearchRunNotFoundError as exc:
            raise OnlyResearchRunIntegrityError("Product Command Receipt points to a missing Research Run") from exc


__all__ = ["OnlyResearchCommandService"]
