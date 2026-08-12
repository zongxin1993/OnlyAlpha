"""Runtime lifecycle orchestrator for checkpoint plus causal execution-tail recovery."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.execution.causal_recovery import (
    OnlyExecutionRecoveryPlanBuilder,
    OnlyExecutionRecoverySession,
)
from onlyalpha.runtime.checkpoint.codec import only_validate_runtime_checkpoint
from onlyalpha.runtime.checkpoint.model import OnlyCheckpointRestoreContext, OnlyRuntimeCheckpoint
from onlyalpha.runtime.checkpoint.registry import OnlyRuntimeCheckpointParticipantRegistry
from onlyalpha.runtime.persistence.store import OnlyRuntimeCheckpointQueryPort
from onlyalpha.runtime.recovery.session import OnlyRuntimeRecoveryDriverResult
from onlyalpha.transaction.persistence_ports import OnlyRuntimeTransactionRecoveryQueryPort

if TYPE_CHECKING:
    from onlyalpha.runtime.recovery.outcome import OnlyRuntimeRecoveryOutcome


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
    continuation_transaction_count: int
    final_boundary_update_id: str | None


class OnlyRuntimeRecoveryOrchestrator:
    def __init__(
        self,
        *,
        runtime_id: OnlyRuntimeId,
        config_fingerprint: str,
        market_composition_fingerprint: str,
        participant_registry: OnlyRuntimeCheckpointParticipantRegistry,
        checkpoint_query: OnlyRuntimeCheckpointQueryPort,
        transaction_query: OnlyRuntimeTransactionRecoveryQueryPort,
        causal_replay: Callable[
            [OnlyRuntimeCheckpoint, OnlyExecutionRecoverySession],
            OnlyRuntimeRecoveryDriverResult,
        ],
    ) -> None:
        self._runtime_id = runtime_id
        self._config_fingerprint = config_fingerprint
        self._market_composition_fingerprint = market_composition_fingerprint
        self._registry = participant_registry
        self._checkpoint_query = checkpoint_query
        self._plan_builder = OnlyExecutionRecoveryPlanBuilder(transaction_query)
        self._causal_replay = causal_replay

    def recover(self) -> OnlyRuntimeRecoveryOutcome | None:
        checkpoint = self._checkpoint_query.latest_checkpoint(self._runtime_id)
        if checkpoint is None:
            return None
        only_validate_runtime_checkpoint(checkpoint)
        if checkpoint.header.market_composition_fingerprint != self._market_composition_fingerprint:
            raise RuntimeError("CHECKPOINT_MARKET_COMPOSITION_FINGERPRINT_MISMATCH")
        if checkpoint.header.config_fingerprint != self._config_fingerprint:
            raise RuntimeError("CHECKPOINT_CONFIG_FINGERPRINT_MISMATCH")
        if checkpoint.header.participant_registry_fingerprint != self._registry.fingerprint:
            raise RuntimeError("CHECKPOINT_PARTICIPANT_REGISTRY_FINGERPRINT_MISMATCH")
        self._registry.restore(
            checkpoint.components,
            OnlyCheckpointRestoreContext(self._runtime_id),
        )
        plan = self._plan_builder.build(
            self._runtime_id,
            checkpoint_sequence=checkpoint.header.checkpoint_sequence,
            covered_execution_sequence=checkpoint.header.covered_execution_sequence,
        )
        session = OnlyExecutionRecoverySession(plan)
        replay_result = self._causal_replay(checkpoint, session) if plan.entries else None
        session.require_tail_resolved()
        ready_count = sum(item.state.value == "READY" for item in plan.entries)
        unprojected_count = len(plan.entries) - ready_count
        continuation_count = 0 if replay_result is None else replay_result.continuation_transaction_count
        final_ready = checkpoint.header.covered_execution_sequence + len(plan.entries) + continuation_count
        status = (
            OnlyRuntimeRecoveryStatus.RESTORED_AND_RECOVERED
            if unprojected_count
            else OnlyRuntimeRecoveryStatus.RESTORED_AND_REHYDRATED
            if ready_count
            else OnlyRuntimeRecoveryStatus.RESTORED
        )
        diagnostic = OnlyRuntimeRecoveryDiagnostic(
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
            0 if replay_result is None else replay_result.catch_up_fact_count,
            continuation_count,
            None if replay_result is None else str(replay_result.final_boundary.update_id),
        )
        from onlyalpha.runtime.recovery.outcome import OnlyRuntimeRecoveryOutcome

        tail_start = checkpoint.header.covered_execution_sequence + 1 if plan.entries else None
        tail_end = checkpoint.header.covered_execution_sequence + len(plan.entries) if plan.entries else None
        continuation_start = tail_end + 1 if tail_end is not None and continuation_count else None
        if continuation_count and continuation_start is None:
            continuation_start = checkpoint.header.covered_execution_sequence + 1
        continuation_end = None if continuation_start is None else continuation_start + continuation_count - 1
        return OnlyRuntimeRecoveryOutcome(
            checkpoint,
            diagnostic,
            tail_start,
            tail_end,
            continuation_start,
            continuation_end,
            None if replay_result is None else replay_result.final_boundary,
            replay_result is not None,
        )
