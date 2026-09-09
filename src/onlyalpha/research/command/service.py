"""Idempotent submission and cancellation application service."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from onlyalpha.application.product_command_authority import (
    OnlyProductCommandAdmissionAuthority,
    OnlyProductCommandAuthorityUnavailableError,
    OnlyProductCommandConflictError,
)
from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandAdmissionV1,
    OnlyProductCommandId,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandOutcomeRef,
    OnlyProductCommandReceipt,
    only_cancel_research_run_command_fingerprint,
)
from onlyalpha.application.runtime_generation import OnlyRuntimeGenerationWorkAuthority
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
    OnlyDerivedResearchSubmitCommandV2,
    OnlyResearchSubmissionKey,
    OnlyResearchSubmitCommand,
    OnlyResearchSubmitDisposition,
    OnlyResearchSubmitOutcome,
    only_derived_research_run_id,
)
from .store import OnlyResearchCommandStore


class OnlyResearchCommandService:
    def __init__(
        self,
        *,
        admission: OnlyResearchRunAdmissionService,
        store: OnlyResearchCommandStore,
        now_utc: Callable[[], datetime],
        runtime_generations: OnlyRuntimeGenerationWorkAuthority,
        command_admissions: OnlyProductCommandAdmissionAuthority | None = None,
        cancellation_cas_attempts: int = 3,
    ) -> None:
        if cancellation_cas_attempts < 1:
            raise ValueError("cancellation_cas_attempts must be positive")
        self._admission = admission
        self._store = store
        self._now_utc = now_utc
        self._runtime_generations = runtime_generations
        self._command_admissions = command_admissions
        self._cancellation_cas_attempts = cancellation_cas_attempts

    def submit_research_run(
        self,
        submission_key: OnlyResearchSubmissionKey,
        specification: OnlyResearchSpecification,
        provenance: OnlyResearchAuthoringProvenance | None = None,
        *,
        parent_runtime_work_id: str | None = None,
    ) -> OnlyResearchSubmitOutcome:
        strict = OnlyResearchSpecification.from_dict(specification.to_dict())
        command: OnlyResearchSubmitCommand | OnlyDerivedResearchSubmitCommandV2
        if parent_runtime_work_id is None:
            command = OnlyResearchSubmitCommand(submission_key, strict, provenance)
        else:
            command = OnlyDerivedResearchSubmitCommandV2(
                submission_key,
                strict,
                parent_runtime_work_id,
                provenance,
            )
            self._admit_derived_command(command)
        existing = self._store.find_product_command_receipt(submission_key)
        if existing is not None:
            run = self._replay_receipt(
                existing,
                kind=OnlyProductCommandKind.CREATE_RESEARCH_RUN,
                fingerprint=command.command_fingerprint,
            )
            self._require_expected_binding(run.run_id.value, parent_runtime_work_id)
            return OnlyResearchSubmitOutcome(OnlyResearchSubmitDisposition.REUSED, run)
        if parent_runtime_work_id is None:
            # Preserve the standalone admission call contract exactly; the new
            # exact identity seam belongs only to derived formal work.
            prepared = self._admission.prepare(strict, provenance=provenance)
            self._runtime_generations.bind_new_work(
                prepared.run_id.value,
                actor="research-product-admission",
                occurred_at=prepared.queued_at,
            )
        else:
            prepared = self._admission.prepare(
                strict,
                provenance=provenance,
                exact_run_id=only_derived_research_run_id(submission_key),
            )
            self._runtime_generations.bind_derived_work(
                parent_runtime_work_id,
                prepared.run_id.value,
                actor="research-product-derived-admission",
                occurred_at=prepared.queued_at,
            )
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
        try:
            record = self._store.create_queued_with_receipt(prepared, requested)
        except Exception:
            if parent_runtime_work_id is None:
                self._runtime_generations.release_work(
                    prepared.run_id.value,
                    actor="research-product-admission-compensation",
                    occurred_at=self._now_utc(),
                )
            raise
        run = self._replay_receipt(
            record,
            kind=OnlyProductCommandKind.CREATE_RESEARCH_RUN,
            fingerprint=command.command_fingerprint,
        )
        if run.run_id != prepared.run_id and parent_runtime_work_id is None:
            self._runtime_generations.release_work(
                prepared.run_id.value,
                actor="research-product-admission-concurrency-loser",
                occurred_at=self._now_utc(),
            )
        self._require_expected_binding(run.run_id.value, parent_runtime_work_id)
        disposition = (
            OnlyResearchSubmitDisposition.CREATED
            if record.outcome_ref.outcome_id == prepared.run_id.value
            else OnlyResearchSubmitDisposition.REUSED
        )
        return OnlyResearchSubmitOutcome(disposition, run)

    def _require_expected_binding(self, run_id: str, parent_runtime_work_id: str | None) -> None:
        child = self._runtime_generations.require_work_binding(run_id)
        if parent_runtime_work_id is None:
            return
        parent = self._runtime_generations.require_work_binding(parent_runtime_work_id)
        if getattr(parent, "runtime_generation_fingerprint", None) != getattr(
            child, "runtime_generation_fingerprint", None
        ):
            raise ValueError("RUNTIME_DERIVED_WORK_GENERATION_BINDING_CONFLICT")

    def _admit_derived_command(self, command: OnlyDerivedResearchSubmitCommandV2) -> None:
        authority = self._command_admissions
        if authority is None:
            raise OnlyResearchRunIntegrityError("Derived Research Product Admission Authority is unavailable")
        requested = OnlyProductCommandAdmissionV1(
            command.submission_key,
            OnlyProductCommandKind.CREATE_RESEARCH_RUN,
            command.command_fingerprint,
        )
        try:
            authority.admit_exact(requested)
            actual = authority.load_admission(command.submission_key)
        except OnlyProductCommandConflictError as exc:
            raise OnlyResearchSubmissionConflictError() from exc
        except OnlyProductCommandAuthorityUnavailableError as exc:
            raise OnlyResearchRunIntegrityError("Derived Research Product Admission Authority is unavailable") from exc
        if actual != requested:
            raise OnlyResearchSubmissionConflictError()

    def request_research_run_cancellation(
        self,
        run_id: OnlyResearchRunId,
        command_id: OnlyProductCommandId | None = None,
    ) -> OnlyResearchRun:
        if command_id is not None:
            fingerprint = only_cancel_research_run_command_fingerprint(run_id.value)
            existing = self._store.find_product_command_receipt(command_id)
            if existing is not None:
                return self._release_if_terminal(
                    self._replay_receipt(
                        existing,
                        kind=OnlyProductCommandKind.CANCEL_RESEARCH_RUN,
                        fingerprint=fingerprint,
                        expected_run_id=run_id,
                    )
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
            return self._release_if_terminal(
                self._replay_receipt(
                    actual,
                    kind=OnlyProductCommandKind.CANCEL_RESEARCH_RUN,
                    fingerprint=fingerprint,
                    expected_run_id=run_id,
                )
            )
        for _ in range(self._cancellation_cas_attempts):
            current = self._store.load(run_id)
            if current.state in {OnlyResearchRunState.CANCEL_REQUESTED, OnlyResearchRunState.CANCELLED}:
                return self._release_if_terminal(current)
            if current.state in {OnlyResearchRunState.COMPLETED, OnlyResearchRunState.FAILED}:
                raise OnlyResearchCancellationConflictError()
            target = (
                OnlyResearchRunState.CANCELLED
                if current.state is OnlyResearchRunState.QUEUED
                else OnlyResearchRunState.CANCEL_REQUESTED
            )
            transitioned = current.transition(target, at=self._now_utc())
            try:
                return self._release_if_terminal(self._store.commit_transition(current, transitioned))
            except OnlyResearchRunRevisionConflictError:
                continue
        raise OnlyResearchCommandConcurrencyError()

    def _release_if_terminal(self, run: OnlyResearchRun) -> OnlyResearchRun:
        if run.state in {
            OnlyResearchRunState.COMPLETED,
            OnlyResearchRunState.FAILED,
            OnlyResearchRunState.CANCELLED,
        }:
            self._runtime_generations.release_work(
                run.run_id.value,
                actor="research-product-terminal-command",
                occurred_at=run.finished_at or self._now_utc(),
            )
        return run

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
