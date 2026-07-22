"""Runtime-owned journal of successfully committed local executions."""

from __future__ import annotations

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.domain.identifiers import OnlyRuntimeId, OnlyTradeId

from .committed import OnlyCommittedExecutionFact


class OnlyCommittedExecutionJournal:
    """Runtime-scoped append-only authority with update and trade idempotency."""

    def __init__(self, runtime_id: OnlyRuntimeId, gateway_ids: tuple[OnlyBrokerGatewayId, ...]) -> None:
        if not gateway_ids:
            raise ValueError("committed execution journal requires at least one Gateway scope")
        self._runtime_id = runtime_id
        self._gateway_ids = frozenset(gateway_ids)
        self._records: list[OnlyCommittedExecutionFact] = []
        self._trade_keys: set[tuple[OnlyRuntimeId, OnlyBrokerGatewayId, OnlyTradeId]] = set()
        self._update_keys: set[tuple[OnlyRuntimeId, OnlyBrokerGatewayId, OnlyBrokerUpdateId]] = set()

    @property
    def next_execution_sequence(self) -> int:
        return len(self._records) + 1

    def append(self, fact: OnlyCommittedExecutionFact) -> bool:
        if fact.runtime_id != self._runtime_id or fact.gateway_id not in self._gateway_ids:
            raise ValueError("committed execution belongs to another Runtime or Gateway scope")
        trade_key = fact.runtime_id, fact.gateway_id, fact.trade_id
        update_key = fact.runtime_id, fact.gateway_id, fact.broker_update_id
        if trade_key in self._trade_keys or update_key in self._update_keys:
            return False
        if fact.execution_sequence != self.next_execution_sequence:
            raise ValueError("committed execution sequence must be contiguous")
        self._trade_keys.add(trade_key)
        self._update_keys.add(update_key)
        self._records.append(fact)
        return True

    def records(self) -> tuple[OnlyCommittedExecutionFact, ...]:
        return tuple(self._records)

    def __len__(self) -> int:
        return len(self._records)


__all__ = ["OnlyCommittedExecutionJournal"]
