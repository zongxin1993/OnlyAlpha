"""Fail-closed coordinator for post-recovery authority finalization."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.cluster.manager import OnlyClusterManager
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.runtime.checkpoint.model import OnlyRuntimeCheckpoint
from onlyalpha.runtime.checkpoint.service import OnlyRuntimeCheckpointService
from onlyalpha.runtime.runtime import OnlyRuntimeError

from .outcome import OnlyRuntimeRecoveryOutcome
from .validation import (
    OnlyPostRecoveryAuthorityValidator,
    OnlyPostRecoveryValidationContext,
    OnlyPostRecoveryValidationReport,
)


def _require_quiescent(context: OnlyPostRecoveryValidationContext) -> None:
    boundary = context.runtime_boundary_view
    if boundary.broker_inbound_count != 0 or boundary.market_data_inbound_count != 0:
        raise RuntimeError("POST_RECOVERY_INBOUND_QUEUE_NOT_EMPTY")
    if boundary.event_bus_pending_count != 0:
        raise RuntimeError("POST_RECOVERY_EVENT_BUS_NOT_DRAINED")


class OnlyRuntimeRecoveryFinalizationPhase(StrEnum):
    CREATED = "CREATED"
    CLUSTER_COMPLETION = "CLUSTER_COMPLETION"
    QUIESCENCE_CHECK = "QUIESCENCE_CHECK"
    AUTHORITY_VALIDATION = "AUTHORITY_VALIDATION"
    CHECKPOINT_CAPTURE = "CHECKPOINT_CAPTURE"
    CHECKPOINT_WRITE = "CHECKPOINT_WRITE"
    CHECKPOINT_VERIFY = "CHECKPOINT_VERIFY"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class OnlyRuntimeRecoveryFinalizationError(OnlyRuntimeError):
    def __init__(
        self,
        *,
        runtime_id: str,
        phase: OnlyRuntimeRecoveryFinalizationPhase,
        original: Exception,
        validation_report: OnlyPostRecoveryValidationReport | None = None,
        expected_checkpoint_sequence: int | None = None,
        durable_checkpoint_sequence: int | None = None,
        code: str = "POST_RECOVERY_FINALIZATION_FAILED",
    ) -> None:
        self.runtime_id = runtime_id
        self.phase = phase
        self.original_error_type = type(original).__name__
        self.original_error_message = str(original)
        self.validation_report = validation_report
        self.expected_checkpoint_sequence = expected_checkpoint_sequence
        self.durable_checkpoint_sequence = durable_checkpoint_sequence
        self.code = code
        super().__init__(f"{code}: phase={phase.value} {self.original_error_type}: {self.original_error_message}")


@dataclass(frozen=True, slots=True)
class OnlyRuntimeRecoveryFinalizationResult:
    outcome: OnlyRuntimeRecoveryOutcome
    validation_report: OnlyPostRecoveryValidationReport
    checkpoint: OnlyRuntimeCheckpoint


class OnlyRuntimeRecoveryFinalizer:
    def __init__(
        self,
        *,
        cluster_manager: OnlyClusterManager,
        event_bus: OnlyEventBus,
        validator: OnlyPostRecoveryAuthorityValidator,
        context_factory: Callable[[OnlyRuntimeRecoveryOutcome], OnlyPostRecoveryValidationContext],
        checkpoint_service: OnlyRuntimeCheckpointService,
        created_at: Callable[[], OnlyTimestamp],
    ) -> None:
        self._cluster_manager = cluster_manager
        self._event_bus = event_bus
        self._validator = validator
        self._context_factory = context_factory
        self._checkpoint_service = checkpoint_service
        self._created_at = created_at
        self._phase = OnlyRuntimeRecoveryFinalizationPhase.CREATED

    @property
    def phase(self) -> OnlyRuntimeRecoveryFinalizationPhase:
        return self._phase

    def finalize(self, outcome: OnlyRuntimeRecoveryOutcome) -> OnlyRuntimeRecoveryFinalizationResult:
        if self._phase is not OnlyRuntimeRecoveryFinalizationPhase.CREATED:
            raise OnlyRuntimeRecoveryFinalizationError(
                runtime_id=str(outcome.restored_checkpoint.header.runtime_id),
                phase=self._phase,
                original=RuntimeError("recovery finalizer may run only once"),
            )
        report: OnlyPostRecoveryValidationReport | None = None
        checkpoint: OnlyRuntimeCheckpoint | None = None
        failure_phase: OnlyRuntimeRecoveryFinalizationPhase = self._phase
        try:
            self._phase = failure_phase = OnlyRuntimeRecoveryFinalizationPhase.CLUSTER_COMPLETION
            self._cluster_manager.begin_recovery_finalization_all()
            self._event_bus.drain()

            self._phase = failure_phase = OnlyRuntimeRecoveryFinalizationPhase.QUIESCENCE_CHECK
            context = self._context_factory(outcome)
            _require_quiescent(context)

            self._phase = failure_phase = OnlyRuntimeRecoveryFinalizationPhase.AUTHORITY_VALIDATION
            report = self._validator.validate(context)
            if not report.passed:
                failed = tuple(item.code for item in report.checks if item.status.value == "FAILED")
                raise RuntimeError(f"POST_RECOVERY_AUTHORITY_VALIDATION_FAILED: {failed}")

            self._phase = failure_phase = OnlyRuntimeRecoveryFinalizationPhase.CHECKPOINT_CAPTURE
            checkpoint = self._checkpoint_service.capture(self._created_at())

            self._phase = failure_phase = OnlyRuntimeRecoveryFinalizationPhase.CHECKPOINT_WRITE
            try:
                self._checkpoint_service.write(checkpoint)
            except Exception as write_error:
                try:
                    durable = self._checkpoint_service.verify_durable(checkpoint)
                except Exception:
                    raise RuntimeError("POST_RECOVERY_CHECKPOINT_WRITE_FAILED") from write_error
                raise OnlyRuntimeRecoveryFinalizationError(
                    runtime_id=str(outcome.restored_checkpoint.header.runtime_id),
                    phase=failure_phase,
                    original=write_error,
                    validation_report=report,
                    expected_checkpoint_sequence=checkpoint.header.checkpoint_sequence,
                    durable_checkpoint_sequence=durable.header.checkpoint_sequence,
                    code="POST_RECOVERY_CHECKPOINT_COMMITTED_BUT_FINALIZATION_INTERRUPTED",
                ) from write_error

            self._phase = failure_phase = OnlyRuntimeRecoveryFinalizationPhase.CHECKPOINT_VERIFY
            verified = self._checkpoint_service.verify_durable(checkpoint)
            self._cluster_manager.mark_recovered_all()
            self._phase = OnlyRuntimeRecoveryFinalizationPhase.COMPLETED
            return OnlyRuntimeRecoveryFinalizationResult(outcome, report, verified)
        except Exception as exc:
            self._phase = OnlyRuntimeRecoveryFinalizationPhase.FAILED
            self._cluster_manager.fail_recovery_finalization_all(exc)
            if isinstance(exc, OnlyRuntimeRecoveryFinalizationError):
                raise
            raise OnlyRuntimeRecoveryFinalizationError(
                runtime_id=str(outcome.restored_checkpoint.header.runtime_id),
                phase=failure_phase,
                original=exc,
                validation_report=report,
                expected_checkpoint_sequence=None if checkpoint is None else checkpoint.header.checkpoint_sequence,
            ) from exc


__all__ = [
    "OnlyRuntimeRecoveryFinalizationError",
    "OnlyRuntimeRecoveryFinalizationPhase",
    "OnlyRuntimeRecoveryFinalizationResult",
    "OnlyRuntimeRecoveryFinalizer",
]
