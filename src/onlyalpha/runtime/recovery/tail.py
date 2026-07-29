"""Multi-transaction tail classification and integrity validation."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.execution.codec import only_committed_execution_transaction_payload_hash
from onlyalpha.execution.persistence_ports import OnlyExecutionTransactionQueryPort
from onlyalpha.execution.transaction import OnlyCommittedExecutionTransaction


@dataclass(frozen=True, slots=True)
class OnlyExecutionTransactionTail:
    checkpoint_sequence: int
    ready_prefix: tuple[OnlyCommittedExecutionTransaction, ...]
    unprojected_suffix: tuple[OnlyCommittedExecutionTransaction, ...]


class OnlyExecutionTransactionTailAnalyzer:
    def __init__(self, query: OnlyExecutionTransactionQueryPort) -> None:
        self._query = query

    def analyze(
        self,
        runtime_id: OnlyRuntimeId,
        *,
        checkpoint_sequence: int,
        covered_execution_sequence: int,
    ) -> OnlyExecutionTransactionTail:
        all_records = self._query.records(runtime_id)
        if covered_execution_sequence > len(all_records):
            raise ValueError("checkpoint covers a transaction that does not exist")
        for expected, transaction in enumerate(all_records, start=1):
            if transaction.execution_sequence != expected:
                raise ValueError("TRANSACTION_TAIL_GAP")
            if only_committed_execution_transaction_payload_hash(transaction) != transaction.committed_payload_hash:
                raise ValueError("TRANSACTION_TAIL_HASH_MISMATCH")
        tail = tuple(item for item in all_records if item.execution_sequence > covered_execution_sequence)
        ready: list[OnlyCommittedExecutionTransaction] = []
        unprojected: list[OnlyCommittedExecutionTransaction] = []
        encountered_unready = False
        for offset, transaction in enumerate(tail, start=covered_execution_sequence + 1):
            if transaction.execution_sequence != offset:
                raise ValueError("TRANSACTION_TAIL_GAP")
            if transaction.projection_ready:
                if encountered_unready:
                    raise ValueError("TRANSACTION_TAIL_ORDER_INVALID")
                ready.append(transaction)
            else:
                encountered_unready = True
                unprojected.append(transaction)
        return OnlyExecutionTransactionTail(checkpoint_sequence, tuple(ready), tuple(unprojected))
