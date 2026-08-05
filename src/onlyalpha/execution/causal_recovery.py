"""Strict causal execution-transaction recovery model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import NoReturn

from onlyalpha.broker.identifiers import OnlyBrokerUpdateId
from onlyalpha.broker.updates import OnlyBrokerInboundUpdate
from onlyalpha.domain.identifiers import OnlyRuntimeId, OnlyTradeId
from onlyalpha.execution.committed import OnlyCommittedExecutionFact
from onlyalpha.execution.terminal_fact import OnlyCommittedTerminalExecutionFact
from onlyalpha.transaction.codec import (
    only_prepared_runtime_transaction_authority_hash,
    only_prepared_runtime_transaction_payload_hash,
)
from onlyalpha.transaction.persistence_ports import OnlyRuntimeTransactionRecoveryQueryPort
from onlyalpha.transaction.transaction import (
    OnlyCommittedRuntimeTransaction,
    OnlyPreparedRuntimeTransaction,
    OnlyStoredRuntimeTransaction,
)


class OnlyExecutionRecoveryError(RuntimeError):
    """Recovery cannot reproduce the durable causal transaction contract."""


class OnlyExecutionRecoveryEntryState(StrEnum):
    READY = "READY"
    UNPROJECTED = "UNPROJECTED"


class OnlyExecutionRecoveryResolution(StrEnum):
    READY_REHYDRATED = "READY_REHYDRATED"
    UNPROJECTED_RECOVERED = "UNPROJECTED_RECOVERED"


class OnlyExecutionRecoveryPhase(StrEnum):
    MATCHING_PERSISTED_TAIL = "MATCHING_PERSISTED_TAIL"
    TAIL_RESOLVED = "TAIL_RESOLVED"
    FAILED = "FAILED"


class OnlyExecutionRecoveryDecisionKind(StrEnum):
    REHYDRATE_READY = "REHYDRATE_READY"
    RECOVER_UNPROJECTED = "RECOVER_UNPROJECTED"
    COMMIT_CONTINUATION = "COMMIT_CONTINUATION"


@dataclass(frozen=True, slots=True)
class OnlyExecutionRecoveryEntry:
    execution_sequence: int
    state: OnlyExecutionRecoveryEntryState
    stored: OnlyStoredRuntimeTransaction

    @property
    def broker_update_id(self) -> object:
        return _prepared_broker_update_id(self.stored.prepared)

    @property
    def trade_id(self) -> object:
        return getattr(self.stored.prepared.fact_draft, "trade_id", None)


@dataclass(frozen=True, slots=True)
class OnlyExecutionRecoveryDecision:
    kind: OnlyExecutionRecoveryDecisionKind
    entry: OnlyExecutionRecoveryEntry | None

    def __post_init__(self) -> None:
        if self.kind is OnlyExecutionRecoveryDecisionKind.COMMIT_CONTINUATION:
            if self.entry is not None:
                raise ValueError("COMMIT_CONTINUATION recovery decision cannot contain a persisted entry")
            return
        if self.entry is None:
            raise ValueError("persisted recovery decision requires an entry")
        expected = (
            OnlyExecutionRecoveryEntryState.READY
            if self.kind is OnlyExecutionRecoveryDecisionKind.REHYDRATE_READY
            else OnlyExecutionRecoveryEntryState.UNPROJECTED
        )
        if self.entry.state is not expected:
            raise ValueError("recovery decision kind and persisted entry state disagree")


@dataclass(frozen=True, slots=True)
class OnlyExecutionRecoveryContinuation:
    execution_sequence: int
    transaction_id: str
    broker_update_id: OnlyBrokerUpdateId
    trade_id: OnlyTradeId | None


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
    def __init__(self, query: OnlyRuntimeTransactionRecoveryQueryPort) -> None:
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
        self._phase = (
            OnlyExecutionRecoveryPhase.TAIL_RESOLVED
            if not plan.entries
            else OnlyExecutionRecoveryPhase.MATCHING_PERSISTED_TAIL
        )
        self._continuations: list[OnlyExecutionRecoveryContinuation] = []

    @property
    def phase(self) -> OnlyExecutionRecoveryPhase:
        return self._phase

    @property
    def tail_resolved(self) -> bool:
        return self._phase is OnlyExecutionRecoveryPhase.TAIL_RESOLVED

    @property
    def next_entry(self) -> OnlyExecutionRecoveryEntry | None:
        return None if self._index == len(self._plan.entries) else self._plan.entries[self._index]

    @property
    def ready_rehydrated_count(self) -> int:
        return sum(item[1] is OnlyExecutionRecoveryResolution.READY_REHYDRATED for item in self._resolutions)

    @property
    def unprojected_recovered_count(self) -> int:
        return sum(item[1] is OnlyExecutionRecoveryResolution.UNPROJECTED_RECOVERED for item in self._resolutions)

    @property
    def continuations(self) -> tuple[OnlyExecutionRecoveryContinuation, ...]:
        return tuple(self._continuations)

    def decide(
        self,
        update: OnlyBrokerInboundUpdate,
        prepared: OnlyPreparedRuntimeTransaction,
    ) -> OnlyExecutionRecoveryDecision:
        self._require_usable()
        if self._phase is OnlyExecutionRecoveryPhase.TAIL_RESOLVED:
            if _prepared_broker_update_id(prepared) != update.update_id:
                self._fail("RECOVERY_CONTINUATION_SCOPE_MISMATCH")
            return OnlyExecutionRecoveryDecision(OnlyExecutionRecoveryDecisionKind.COMMIT_CONTINUATION, None)
        entry = self.next_entry
        if entry is None:
            self._fail("RECOVERY_TRANSACTION_MISSING")
        expected = entry.stored.prepared
        if (
            _prepared_broker_update_id(expected) != update.update_id
            or expected.transaction_id != prepared.transaction_id
        ):
            later = any(
                _prepared_broker_update_id(candidate.stored.prepared) == update.update_id
                or candidate.stored.prepared.transaction_id == prepared.transaction_id
                for candidate in self._plan.entries[self._index + 1 :]
            )
            code = "RECOVERY_TRANSACTION_CAUSAL_ORDER_MISMATCH" if later else "RECOVERY_TRANSACTION_MISSING"
            self._fail(code)
        if prepared != expected:
            mismatches = tuple(
                name for name in prepared.__dataclass_fields__ if getattr(prepared, name) != getattr(expected, name)
            )
            prepared_fact = prepared.fact_draft.to_dict()
            expected_fact = expected.fact_draft.to_dict()
            fact_mismatches = tuple(
                name
                for name in sorted(prepared_fact.keys() | expected_fact.keys())
                if prepared_fact.get(name) != expected_fact.get(name)
            )
            processing_detail = (
                f" expected_processing={getattr(expected.fact_draft, 'processing_sequence', None)}"
                f" actual_processing={getattr(prepared.fact_draft, 'processing_sequence', None)}"
            )
            self._fail(
                "RECOVERY_PREPARED_TRANSACTION_MISMATCH: "
                f"fields={','.join(mismatches)} fact_fields={','.join(fact_mismatches)}{processing_detail}"
            )
        try:
            authority_hash = only_prepared_runtime_transaction_authority_hash(prepared)
            payload_hash = only_prepared_runtime_transaction_payload_hash(prepared)
        except ValueError as exc:
            self._phase = OnlyExecutionRecoveryPhase.FAILED
            raise OnlyExecutionRecoveryError("RECOVERY_TRANSACTION_CODEC_OR_HASH_MISMATCH") from exc
        if authority_hash != expected.authority_hash or payload_hash != expected.payload_hash:
            self._fail("RECOVERY_TRANSACTION_CODEC_OR_HASH_MISMATCH")
        kind = (
            OnlyExecutionRecoveryDecisionKind.REHYDRATE_READY
            if entry.state is OnlyExecutionRecoveryEntryState.READY
            else OnlyExecutionRecoveryDecisionKind.RECOVER_UNPROJECTED
        )
        return OnlyExecutionRecoveryDecision(kind, entry)

    def resolve_persisted(self, execution_sequence: int, resolution: OnlyExecutionRecoveryResolution) -> None:
        self._require_usable()
        if self._phase is not OnlyExecutionRecoveryPhase.MATCHING_PERSISTED_TAIL:
            self._fail("RECOVERY_TRANSACTION_CAUSAL_ORDER_MISMATCH")
        entry = self.next_entry
        if entry is None or entry.execution_sequence != execution_sequence:
            self._fail("RECOVERY_TRANSACTION_CAUSAL_ORDER_MISMATCH")
        expected_resolution = (
            OnlyExecutionRecoveryResolution.READY_REHYDRATED
            if entry.state is OnlyExecutionRecoveryEntryState.READY
            else OnlyExecutionRecoveryResolution.UNPROJECTED_RECOVERED
        )
        if resolution is not expected_resolution:
            self._fail("RECOVERY_TRANSACTION_STATE_MISMATCH")
        self._resolutions.append((execution_sequence, resolution))
        self._index += 1
        if self._index == len(self._plan.entries):
            self._phase = OnlyExecutionRecoveryPhase.TAIL_RESOLVED

    def record_continuation(self, transaction: OnlyCommittedRuntimeTransaction) -> None:
        self._require_usable()
        if self._phase is not OnlyExecutionRecoveryPhase.TAIL_RESOLVED:
            self._fail("RECOVERY_CONTINUATION_BEFORE_TAIL_RESOLVED")
        expected_sequence = (
            self._plan.covered_execution_sequence + len(self._plan.entries) + 1
            if not self._continuations
            else self._continuations[-1].execution_sequence + 1
        )
        if transaction.execution_sequence != expected_sequence:
            self._fail(
                "RECOVERY_CONTINUATION_SEQUENCE_MISMATCH: "
                f"expected={expected_sequence} actual={transaction.execution_sequence}"
            )
        if not transaction.projection_ready:
            self._fail("RECOVERY_CONTINUATION_TRANSACTION_NOT_READY")
        if transaction.runtime_id != self._plan.runtime_id:
            self._fail("RECOVERY_CONTINUATION_SCOPE_MISMATCH")
        if not isinstance(transaction.fact, OnlyCommittedExecutionFact | OnlyCommittedTerminalExecutionFact):
            self._fail("RECOVERY_TRANSACTION_IS_NOT_BROKER_DRIVEN")
        continuation = OnlyExecutionRecoveryContinuation(
            transaction.execution_sequence,
            transaction.transaction_id,
            transaction.fact.broker_update_id,
            getattr(transaction.fact, "trade_id", None),
        )
        if any(
            item.transaction_id == continuation.transaction_id
            or item.broker_update_id == continuation.broker_update_id
            or (continuation.trade_id is not None and item.trade_id == continuation.trade_id)
            for item in self._continuations
        ):
            self._fail("RECOVERY_CONTINUATION_SCOPE_MISMATCH")
        self._continuations.append(continuation)

    def require_tail_resolved(self) -> None:
        self._require_usable()
        if self._phase is not OnlyExecutionRecoveryPhase.TAIL_RESOLVED:
            entry = self.next_entry
            sequence = None if entry is None else entry.execution_sequence
            raise OnlyExecutionRecoveryError(f"RECOVERY_TRANSACTION_TAIL_INCOMPLETE: sequence={sequence}")

    def _require_usable(self) -> None:
        if self._phase is OnlyExecutionRecoveryPhase.FAILED:
            raise OnlyExecutionRecoveryError("RECOVERY_SESSION_FAILED")

    def _fail(self, message: str) -> NoReturn:
        self._phase = OnlyExecutionRecoveryPhase.FAILED
        raise OnlyExecutionRecoveryError(message)


def _prepared_broker_update_id(prepared: OnlyPreparedRuntimeTransaction) -> OnlyBrokerUpdateId:
    update_id = getattr(prepared.fact_draft, "broker_update_id", None)
    if not isinstance(update_id, OnlyBrokerUpdateId):
        raise OnlyExecutionRecoveryError("RECOVERY_TRANSACTION_IS_NOT_BROKER_DRIVEN")
    return update_id
