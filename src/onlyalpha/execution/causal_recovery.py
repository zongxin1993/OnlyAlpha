"""Strict causal execution-transaction recovery model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.broker.updates import OnlyBrokerTradeUpdate
from onlyalpha.domain.identifiers import OnlyRuntimeId

from .codec import (
    only_prepared_execution_transaction_authority_hash,
    only_prepared_execution_transaction_payload_hash,
)
from .persistence_ports import OnlyExecutionTransactionRecoveryQueryPort
from .transaction import OnlyPreparedExecutionTransaction, OnlyStoredExecutionTransaction


class OnlyExecutionRecoveryError(RuntimeError):
    """Recovery cannot reproduce the durable causal transaction contract."""


class OnlyExecutionRecoveryEntryState(StrEnum):
    READY = "READY"
    UNPROJECTED = "UNPROJECTED"


class OnlyExecutionRecoveryResolution(StrEnum):
    READY_REHYDRATED = "READY_REHYDRATED"
    UNPROJECTED_RECOVERED = "UNPROJECTED_RECOVERED"


@dataclass(frozen=True, slots=True)
class OnlyExecutionRecoveryEntry:
    execution_sequence: int
    state: OnlyExecutionRecoveryEntryState
    stored: OnlyStoredExecutionTransaction

    @property
    def broker_update_id(self) -> object:
        return self.stored.prepared.broker_update_id

    @property
    def trade_id(self) -> object:
        return self.stored.prepared.trade_id


@dataclass(frozen=True, slots=True)
class OnlyExecutionRecoveryPlan:
    runtime_id: OnlyRuntimeId
    checkpoint_sequence: int
    covered_execution_sequence: int
    entries: tuple[OnlyExecutionRecoveryEntry, ...]

    def __post_init__(self) -> None:
        expected = tuple(
            range(self.covered_execution_sequence + 1, self.covered_execution_sequence + 1 + len(self.entries))
        )
        actual = tuple(item.execution_sequence for item in self.entries)
        if actual != expected:
            raise OnlyExecutionRecoveryError("RECOVERY_TRANSACTION_CAUSAL_ORDER_MISMATCH")
        encountered_unprojected = False
        for entry in self.entries:
            if entry.state is OnlyExecutionRecoveryEntryState.UNPROJECTED:
                encountered_unprojected = True
            elif encountered_unprojected:
                raise OnlyExecutionRecoveryError("RECOVERY_TRANSACTION_CAUSAL_ORDER_MISMATCH")


class OnlyExecutionRecoveryPlanBuilder:
    def __init__(self, query: OnlyExecutionTransactionRecoveryQueryPort) -> None:
        self._query = query

    def build(
        self,
        runtime_id: OnlyRuntimeId,
        *,
        checkpoint_sequence: int,
        covered_execution_sequence: int,
    ) -> OnlyExecutionRecoveryPlan:
        records = self._query.recovery_records(runtime_id, after_sequence=covered_execution_sequence)
        entries = tuple(
            OnlyExecutionRecoveryEntry(
                record.committed.execution_sequence,
                OnlyExecutionRecoveryEntryState.READY
                if record.committed.projection_ready
                else OnlyExecutionRecoveryEntryState.UNPROJECTED,
                record,
            )
            for record in records
        )
        return OnlyExecutionRecoveryPlan(runtime_id, checkpoint_sequence, covered_execution_sequence, entries)


class OnlyExecutionRecoverySession:
    """Owns ordered update-time resolution for one restored transaction tail."""

    def __init__(self, plan: OnlyExecutionRecoveryPlan) -> None:
        self._plan = plan
        self._index = 0
        self._resolutions: list[tuple[int, OnlyExecutionRecoveryResolution]] = []
        self._boundary_complete = False

    @property
    def complete(self) -> bool:
        return self._index == len(self._plan.entries)

    @property
    def next_entry(self) -> OnlyExecutionRecoveryEntry | None:
        return None if self.complete else self._plan.entries[self._index]

    @property
    def ready_rehydrated_count(self) -> int:
        return sum(item[1] is OnlyExecutionRecoveryResolution.READY_REHYDRATED for item in self._resolutions)

    @property
    def unprojected_recovered_count(self) -> int:
        return sum(item[1] is OnlyExecutionRecoveryResolution.UNPROJECTED_RECOVERED for item in self._resolutions)

    @property
    def boundary_complete(self) -> bool:
        return self._boundary_complete

    def require_expected(
        self,
        update: OnlyBrokerTradeUpdate,
        prepared: OnlyPreparedExecutionTransaction,
    ) -> OnlyExecutionRecoveryEntry:
        entry = self.next_entry
        if entry is None:
            raise OnlyExecutionRecoveryError("RECOVERY_TRANSACTION_MISSING")
        expected = entry.stored.prepared
        if (
            expected.broker_update_id != update.update_id
            or expected.trade_id != update.fill.trade_id
            or expected.transaction_id != prepared.transaction_id
        ):
            later = any(
                candidate.stored.prepared.broker_update_id == update.update_id
                or candidate.stored.prepared.trade_id == update.fill.trade_id
                for candidate in self._plan.entries[self._index + 1 :]
            )
            code = "RECOVERY_TRANSACTION_CAUSAL_ORDER_MISMATCH" if later else "RECOVERY_TRANSACTION_MISSING"
            raise OnlyExecutionRecoveryError(code)
        if prepared != expected:
            mismatches = tuple(
                name for name in prepared.__dataclass_fields__ if getattr(prepared, name) != getattr(expected, name)
            )
            fact_mismatches = tuple(
                name
                for name in prepared.fact_draft.__dataclass_fields__
                if getattr(prepared.fact_draft, name) != getattr(expected.fact_draft, name)
            )
            processing_detail = (
                f" expected_processing={expected.fact_draft.processing_sequence}"
                f" actual_processing={prepared.fact_draft.processing_sequence}"
            )
            raise OnlyExecutionRecoveryError(
                "RECOVERY_PREPARED_TRANSACTION_MISMATCH: "
                f"fields={','.join(mismatches)} fact_fields={','.join(fact_mismatches)}{processing_detail}"
            )
        try:
            authority_hash = only_prepared_execution_transaction_authority_hash(prepared)
            payload_hash = only_prepared_execution_transaction_payload_hash(prepared)
        except ValueError as exc:
            raise OnlyExecutionRecoveryError("RECOVERY_TRANSACTION_CODEC_OR_HASH_MISMATCH") from exc
        if authority_hash != expected.authority_hash or payload_hash != expected.payload_hash:
            raise OnlyExecutionRecoveryError("RECOVERY_TRANSACTION_CODEC_OR_HASH_MISMATCH")
        return entry

    def resolve(self, execution_sequence: int, resolution: OnlyExecutionRecoveryResolution) -> None:
        entry = self.next_entry
        if entry is None or entry.execution_sequence != execution_sequence:
            raise OnlyExecutionRecoveryError("RECOVERY_TRANSACTION_CAUSAL_ORDER_MISMATCH")
        expected_resolution = (
            OnlyExecutionRecoveryResolution.READY_REHYDRATED
            if entry.state is OnlyExecutionRecoveryEntryState.READY
            else OnlyExecutionRecoveryResolution.UNPROJECTED_RECOVERED
        )
        if resolution is not expected_resolution:
            raise OnlyExecutionRecoveryError("RECOVERY_TRANSACTION_STATE_MISMATCH")
        self._resolutions.append((execution_sequence, resolution))
        self._index += 1

    def complete_boundary(self) -> None:
        self.require_complete()
        self._boundary_complete = True

    def require_complete(self) -> None:
        if not self.complete:
            entry = self.next_entry
            sequence = None if entry is None else entry.execution_sequence
            raise OnlyExecutionRecoveryError(f"RECOVERY_TRANSACTION_TAIL_INCOMPLETE: sequence={sequence}")
