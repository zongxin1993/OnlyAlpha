"""Atomic checkpoint capture service used only at stable Runtime barriers."""

from __future__ import annotations

from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.runtime.persistence.store import (
    OnlyRuntimeCheckpointQueryPort,
    OnlyRuntimeCheckpointWritePort,
)
from onlyalpha.transaction.persistence_ports import (
    OnlyRuntimeTransactionOutboxPort,
    OnlyRuntimeTransactionQueryPort,
)

from .codec import only_seal_runtime_checkpoint, only_validate_runtime_checkpoint
from .model import (
    ONLY_RUNTIME_CHECKPOINT_SCHEMA_VERSION,
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
        market_composition_fingerprint: str,
        registry: OnlyRuntimeCheckpointParticipantRegistry,
        write_port: OnlyRuntimeCheckpointWritePort,
        query_port: OnlyRuntimeCheckpointQueryPort,
        transaction_query: OnlyRuntimeTransactionQueryPort,
        outbox_port: OnlyRuntimeTransactionOutboxPort,
        retain_last: int,
    ) -> None:
        self._runtime_id = runtime_id
        self._config_fingerprint = config_fingerprint
        self._market_composition_fingerprint = market_composition_fingerprint
        self._registry = registry
        self._write_port = write_port
        self._query_port = query_port
        self._transaction_query = transaction_query
        self._outbox_port = outbox_port
        self._retain_last = retain_last

    def capture(self, created_at: OnlyTimestamp) -> OnlyRuntimeCheckpoint:
        transactions = self._transaction_query.records(self._runtime_id)
        covered = 0
        for item in transactions:
            if item.execution_sequence != covered + 1 or not item.projection_ready:
                raise RuntimeError("checkpoint barrier requires a contiguous projection-ready transaction prefix")
            covered = item.execution_sequence
        previous = self._query_port.latest_checkpoint(self._runtime_id)
        sequence = 1 if previous is None else previous.header.checkpoint_sequence + 1
        context = OnlyCheckpointCaptureContext(self._runtime_id, created_at, covered)
        components = self._registry.capture(context)
        header = OnlyRuntimeCheckpointHeader(
            self._runtime_id,
            sequence,
            covered,
            ONLY_RUNTIME_CHECKPOINT_SCHEMA_VERSION,
            created_at,
            self._config_fingerprint,
            self._market_composition_fingerprint,
            self._registry.fingerprint,
            "pending",
            self._outbox_port.pending_count(self._runtime_id),
        )
        checkpoint = only_seal_runtime_checkpoint(header, components)
        self._registry.validate_components(checkpoint.components)
        return checkpoint

    def write(self, checkpoint: OnlyRuntimeCheckpoint) -> None:
        only_validate_runtime_checkpoint(checkpoint)
        if checkpoint.header.runtime_id != self._runtime_id:
            raise RuntimeError("POST_RECOVERY_CHECKPOINT_IDENTITY_MISMATCH")
        self._write_port.write_checkpoint(checkpoint, retain_last=self._retain_last)

    def verify_durable(self, expected: OnlyRuntimeCheckpoint) -> OnlyRuntimeCheckpoint:
        actual = self._query_port.latest_checkpoint(self._runtime_id)
        if actual is None:
            raise RuntimeError("POST_RECOVERY_CHECKPOINT_NOT_DURABLE")
        try:
            only_validate_runtime_checkpoint(actual)
        except Exception as exc:
            raise RuntimeError("POST_RECOVERY_CHECKPOINT_NOT_DURABLE") from exc
        expected_header = expected.header
        actual_header = actual.header
        identity = (
            actual_header.runtime_id == expected_header.runtime_id
            and actual_header.checkpoint_sequence == expected_header.checkpoint_sequence
            and actual_header.covered_execution_sequence == expected_header.covered_execution_sequence
            and actual_header.checkpoint_schema_version == expected_header.checkpoint_schema_version
            and actual_header.created_at == expected_header.created_at
            and actual_header.config_fingerprint == expected_header.config_fingerprint
            and actual_header.market_composition_fingerprint == expected_header.market_composition_fingerprint
            and actual_header.participant_registry_fingerprint == expected_header.participant_registry_fingerprint
            and actual_header.pending_outbox_count == expected_header.pending_outbox_count
        )
        if not identity:
            raise RuntimeError("POST_RECOVERY_CHECKPOINT_IDENTITY_MISMATCH")
        if actual_header.aggregate_payload_hash != expected_header.aggregate_payload_hash:
            raise RuntimeError("POST_RECOVERY_CHECKPOINT_HASH_MISMATCH")
        if actual.components != expected.components:
            raise RuntimeError("POST_RECOVERY_CHECKPOINT_COMPONENT_MISMATCH")
        return actual

    def create(self, created_at: OnlyTimestamp) -> OnlyRuntimeCheckpoint:
        checkpoint = self.capture(created_at)
        self.write(checkpoint)
        return checkpoint

    def create_verified(self, created_at: OnlyTimestamp) -> OnlyRuntimeCheckpoint:
        checkpoint = self.create(created_at)
        return self.verify_durable(checkpoint)
