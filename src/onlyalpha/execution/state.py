"""Runtime-local Execution deduplication, sequence, audit and reconciliation state."""

from __future__ import annotations

from typing import Protocol

from onlyalpha.broker.identifiers import OnlyBrokerUpdateId
from onlyalpha.execution.models import OnlyExecutionAuditRecord, OnlyExecutionReconciliationRequest


class OnlyExecutionUpdateDeduplicator:
    def __init__(self) -> None:
        self._updates: set[OnlyBrokerUpdateId] = set()
        self._trades: set[str] = set()

    def contains_update(self, update_id: OnlyBrokerUpdateId) -> bool:
        return update_id in self._updates

    def contains_trade(self, fingerprints: tuple[str, ...]) -> bool:
        return any(item in self._trades for item in fingerprints)

    def remember(self, update_id: OnlyBrokerUpdateId, trade_fingerprints: tuple[str, ...] = ()) -> None:
        self._updates.add(update_id)
        self._trades.update(trade_fingerprints)

    def capture_checkpoint(self) -> object:
        return {
            "trades": sorted(self._trades),
            "updates": sorted(str(item) for item in self._updates),
        }

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, dict):
            raise ValueError("Execution dedup checkpoint must be an object")
        self._updates = {OnlyBrokerUpdateId(str(item)) for item in payload["updates"]}
        self._trades = {str(item) for item in payload["trades"]}


class OnlyExecutionSequenceTracker:
    def __init__(self) -> None:
        self._last: dict[tuple[str, ...], int] = {}

    def is_stale(self, scope: tuple[str, ...], source_sequence: int) -> bool:
        previous = self._last.get(scope)
        return previous is not None and source_sequence < previous

    def observe(self, scope: tuple[str, ...], source_sequence: int) -> None:
        self._last[scope] = max(source_sequence, self._last.get(scope, source_sequence))

    def capture_checkpoint(self) -> object:
        return [[list(scope), sequence] for scope, sequence in sorted(self._last.items())]

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, list):
            raise ValueError("Execution sequence checkpoint must be an array")
        self._last = {(tuple(str(part) for part in scope)): int(sequence) for scope, sequence in payload}


class OnlyExecutionAuditStore(Protocol):
    def append(self, record: OnlyExecutionAuditRecord) -> None: ...

    def records(self) -> tuple[OnlyExecutionAuditRecord, ...]: ...


class OnlyInMemoryExecutionAuditStore:
    def __init__(self) -> None:
        self._records: list[OnlyExecutionAuditRecord] = []

    def append(self, record: OnlyExecutionAuditRecord) -> None:
        self._records.append(record)

    def records(self) -> tuple[OnlyExecutionAuditRecord, ...]:
        return tuple(self._records)

    def capture_checkpoint(self) -> object:
        return [item.to_json() for item in self._records]

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, list):
            raise ValueError("Execution audit checkpoint must be an array")
        self._records = [OnlyExecutionAuditRecord.from_json(str(item)) for item in payload]


class OnlyExecutionReconciliationPort(Protocol):
    def request_reconciliation(self, request: OnlyExecutionReconciliationRequest) -> None: ...


class OnlyInMemoryExecutionReconciliationQueue:
    def __init__(self) -> None:
        self._requests: list[OnlyExecutionReconciliationRequest] = []

    def request_reconciliation(self, request: OnlyExecutionReconciliationRequest) -> None:
        self._requests.append(request)

    def requests(self) -> tuple[OnlyExecutionReconciliationRequest, ...]:
        return tuple(self._requests)

    def capture_checkpoint(self) -> object:
        return [item.to_json() for item in self._requests]

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, list):
            raise ValueError("Execution reconciliation checkpoint must be an array")
        self._requests = [OnlyExecutionReconciliationRequest.from_json(str(item)) for item in payload]
