"""Runtime lifecycle orchestrator for checkpoint plus execution-tail recovery."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.execution import OnlyExecutionRecoveryService
from onlyalpha.execution.persistence_ports import OnlyExecutionTransactionQueryPort
from onlyalpha.runtime.checkpoint.codec import only_validate_runtime_checkpoint
from onlyalpha.runtime.checkpoint.model import OnlyCheckpointRestoreContext, OnlyRuntimeCheckpoint
from onlyalpha.runtime.checkpoint.registry import OnlyRuntimeCheckpointParticipantRegistry
from onlyalpha.runtime.persistence.store import OnlyRuntimeCheckpointQueryPort

from .ready_tail_rehydration import OnlyExecutionReadyTailRehydrationService
from .tail import OnlyExecutionTransactionTail, OnlyExecutionTransactionTailAnalyzer


class OnlyRuntimeRecoveryStatus(StrEnum):
    NEW_RUNTIME_INITIALIZED = "NEW_RUNTIME_INITIALIZED"
    RESTORED = "RESTORED"
    RESTORED_AND_REHYDRATED = "RESTORED_AND_REHYDRATED"
    RESTORED_AND_RECOVERED = "RESTORED_AND_RECOVERED"


@dataclass(frozen=True, slots=True)
class OnlyRuntimeRecoveryDiagnostic:
    status: OnlyRuntimeRecoveryStatus
    checkpoint_sequence: int
    covered_execution_sequence: int
    restored_participant_count: int
    ready_tail_count: int
    rehydrated_transaction_count: int
    unprojected_tail_count: int
    recovered_transaction_count: int
    final_ready_sequence: int
    pending_outbox_count: int
    catch_up_bar_count: int


class OnlyRuntimeRecoveryOrchestrator:
    def __init__(
        self,
        *,
        runtime_id: OnlyRuntimeId,
        config_fingerprint: str,
        participant_registry: OnlyRuntimeCheckpointParticipantRegistry,
        checkpoint_query: OnlyRuntimeCheckpointQueryPort,
        transaction_query: OnlyExecutionTransactionQueryPort,
        ready_rehydration: OnlyExecutionReadyTailRehydrationService,
        execution_recovery: OnlyExecutionRecoveryService,
        catch_up: Callable[[OnlyRuntimeCheckpoint, OnlyExecutionTransactionTail], int],
    ) -> None:
        self._runtime_id = runtime_id
        self._config_fingerprint = config_fingerprint
        self._registry = participant_registry
        self._checkpoint_query = checkpoint_query
        self._tail = OnlyExecutionTransactionTailAnalyzer(transaction_query)
        self._ready_rehydration = ready_rehydration
        self._execution_recovery = execution_recovery
        self._catch_up = catch_up

    def recover(self) -> OnlyRuntimeRecoveryDiagnostic | None:
        checkpoint = self._checkpoint_query.latest_checkpoint(self._runtime_id)
        if checkpoint is None:
            return None
        only_validate_runtime_checkpoint(checkpoint)
        if checkpoint.header.config_fingerprint != self._config_fingerprint:
            raise RuntimeError("CHECKPOINT_CONFIG_FINGERPRINT_MISMATCH")
        if checkpoint.header.participant_registry_fingerprint != self._registry.fingerprint:
            raise RuntimeError("CHECKPOINT_PARTICIPANT_REGISTRY_FINGERPRINT_MISMATCH")
        self._registry.restore(
            checkpoint.components,
            OnlyCheckpointRestoreContext(self._runtime_id, checkpoint.header.replay_cursor),
        )
        tail = self._tail.analyze(
            self._runtime_id,
            checkpoint_sequence=checkpoint.header.checkpoint_sequence,
            covered_execution_sequence=checkpoint.header.covered_execution_sequence,
        )
        catch_up_count = self._catch_up(checkpoint, tail) if tail.ready_prefix or tail.unprojected_suffix else 0
        if catch_up_count:
            tail = self._tail.analyze(
                self._runtime_id,
                checkpoint_sequence=checkpoint.header.checkpoint_sequence,
                covered_execution_sequence=checkpoint.header.covered_execution_sequence,
            )
        rehydrated = self._ready_rehydration.rehydrate(tail.ready_prefix)
        recovered_result = self._execution_recovery.recover(self._runtime_id)
        if not recovered_result.succeeded:
            raise RuntimeError(
                "UNPROJECTED_TAIL_RECOVERY_FAILED: "
                f"sequence={recovered_result.failed_sequence} "
                f"component={recovered_result.failure_component} "
                f"error={recovered_result.error}"
            )
        final_ready = (
            checkpoint.header.covered_execution_sequence + rehydrated + recovered_result.completed_transactions
        )
        status = (
            OnlyRuntimeRecoveryStatus.RESTORED_AND_RECOVERED
            if tail.unprojected_suffix
            else OnlyRuntimeRecoveryStatus.RESTORED_AND_REHYDRATED
            if tail.ready_prefix
            else OnlyRuntimeRecoveryStatus.RESTORED
        )
        return OnlyRuntimeRecoveryDiagnostic(
            status,
            checkpoint.header.checkpoint_sequence,
            checkpoint.header.covered_execution_sequence,
            len(checkpoint.components),
            len(tail.ready_prefix),
            rehydrated,
            len(tail.unprojected_suffix),
            recovered_result.completed_transactions,
            final_ready,
            checkpoint.header.pending_outbox_count,
            catch_up_count,
        )
