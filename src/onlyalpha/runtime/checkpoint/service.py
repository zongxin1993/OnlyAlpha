"""Atomic checkpoint capture service used only at stable Runtime barriers."""

from __future__ import annotations

from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.execution.persistence_ports import (
    OnlyExecutionTransactionOutboxPort,
    OnlyExecutionTransactionQueryPort,
)
from onlyalpha.runtime.persistence.store import (
    OnlyRuntimeCheckpointQueryPort,
    OnlyRuntimeCheckpointWritePort,
)

from .codec import only_seal_runtime_checkpoint
from .model import (
    ONLY_RUNTIME_CHECKPOINT_SCHEMA_VERSION,
    OnlyBacktestReplayCursor,
    OnlyCheckpointCaptureContext,
    OnlyRuntimeCheckpoint,
    OnlyRuntimeCheckpointHeader,
)
from .registry import OnlyRuntimeCheckpointParticipantRegistry


class OnlyRuntimeCheckpointService:
    def __init__(
        self,
        *,
        runtime_id: OnlyRuntimeId,
        config_fingerprint: str,
        registry: OnlyRuntimeCheckpointParticipantRegistry,
        write_port: OnlyRuntimeCheckpointWritePort,
        query_port: OnlyRuntimeCheckpointQueryPort,
        transaction_query: OnlyExecutionTransactionQueryPort,
        outbox_port: OnlyExecutionTransactionOutboxPort,
        retain_last: int,
    ) -> None:
        self._runtime_id = runtime_id
        self._config_fingerprint = config_fingerprint
        self._registry = registry
        self._write_port = write_port
        self._query_port = query_port
        self._transaction_query = transaction_query
        self._outbox_port = outbox_port
        self._retain_last = retain_last

    def create(self, cursor: OnlyBacktestReplayCursor, created_at: OnlyTimestamp) -> OnlyRuntimeCheckpoint:
        transactions = self._transaction_query.records(self._runtime_id)
        covered = 0
        for item in transactions:
            if item.execution_sequence != covered + 1 or not item.projection_ready:
                raise RuntimeError("checkpoint barrier requires a contiguous projection-ready transaction prefix")
            covered = item.execution_sequence
        previous = self._query_port.latest_checkpoint(self._runtime_id)
        sequence = 1 if previous is None else previous.header.checkpoint_sequence + 1
        context = OnlyCheckpointCaptureContext(self._runtime_id, created_at, cursor, covered)
        components = self._registry.capture(context)
        header = OnlyRuntimeCheckpointHeader(
            self._runtime_id,
            sequence,
            covered,
            ONLY_RUNTIME_CHECKPOINT_SCHEMA_VERSION,
            created_at,
            cursor,
            self._config_fingerprint,
            self._registry.fingerprint,
            "pending",
            self._outbox_port.pending_count(self._runtime_id),
        )
        checkpoint = only_seal_runtime_checkpoint(header, components)
        self._registry.validate_components(checkpoint.components)
        self._write_port.write_checkpoint(checkpoint, retain_last=self._retain_last)
        return checkpoint
