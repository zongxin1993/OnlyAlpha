"""Runtime lifecycle orchestrator for checkpoint plus causal execution-tail recovery."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.execution import (
    OnlyExecutionRecoveryPlanBuilder,
    OnlyExecutionRecoverySession,
    OnlyExecutionTransactionRecoveryQueryPort,
)
from onlyalpha.runtime.checkpoint.codec import only_validate_runtime_checkpoint
from onlyalpha.runtime.checkpoint.model import OnlyCheckpointRestoreContext, OnlyRuntimeCheckpoint
from onlyalpha.runtime.checkpoint.registry import OnlyRuntimeCheckpointParticipantRegistry
from onlyalpha.runtime.persistence.store import OnlyRuntimeCheckpointQueryPort


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
        transaction_query: OnlyExecutionTransactionRecoveryQueryPort,
        causal_replay: Callable[[OnlyRuntimeCheckpoint, OnlyExecutionRecoverySession], int],
    ) -> None:
        self._runtime_id = runtime_id
        self._config_fingerprint = config_fingerprint
        self._registry = participant_registry
        self._checkpoint_query = checkpoint_query
        self._plan_builder = OnlyExecutionRecoveryPlanBuilder(transaction_query)
        self._causal_replay = causal_replay

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
        plan = self._plan_builder.build(
            self._runtime_id,
            checkpoint_sequence=checkpoint.header.checkpoint_sequence,
            covered_execution_sequence=checkpoint.header.covered_execution_sequence,
        )
        session = OnlyExecutionRecoverySession(plan)
        catch_up_count = self._causal_replay(checkpoint, session) if plan.entries else 0
        session.require_complete()
        ready_count = sum(item.state.value == "READY" for item in plan.entries)
        unprojected_count = len(plan.entries) - ready_count
        final_ready = checkpoint.header.covered_execution_sequence + len(plan.entries)
        status = (
            OnlyRuntimeRecoveryStatus.RESTORED_AND_RECOVERED
            if unprojected_count
            else OnlyRuntimeRecoveryStatus.RESTORED_AND_REHYDRATED
            if ready_count
            else OnlyRuntimeRecoveryStatus.RESTORED
        )
        return OnlyRuntimeRecoveryDiagnostic(
            status,
            checkpoint.header.checkpoint_sequence,
            checkpoint.header.covered_execution_sequence,
            len(checkpoint.components),
            ready_count,
            session.ready_rehydrated_count,
            unprojected_count,
            session.unprojected_recovered_count,
            final_ready,
            checkpoint.header.pending_outbox_count,
            catch_up_count,
        )
