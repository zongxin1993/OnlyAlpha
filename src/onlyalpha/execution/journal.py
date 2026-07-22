"""Runtime-owned journal of successfully applied Broker trades."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.broker.updates import OnlyBrokerTradeUpdate
from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.execution import OnlyOrderFill
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyOrderId, OnlyRuntimeId, OnlyTradeId


@dataclass(frozen=True, slots=True)
class OnlyAppliedTradeFact(OnlyDomainModel):
    runtime_id: OnlyRuntimeId
    gateway_id: OnlyBrokerGatewayId
    account_id: OnlyAccountId
    order_id: OnlyOrderId
    trade_id: OnlyTradeId
    update_id: OnlyBrokerUpdateId
    source_sequence: int
    fill: OnlyOrderFill

    @classmethod
    def from_update(cls, update: OnlyBrokerTradeUpdate) -> OnlyAppliedTradeFact:
        return cls(
            update.runtime_id,
            update.gateway_id,
            update.account_id,
            update.order_id,
            update.fill.trade_id,
            update.update_id,
            update.source_sequence,
            update.fill,
        )


class OnlyAppliedTradeJournal:
    """Append-only authority for trades committed by ExecutionProcessor."""

    def __init__(self) -> None:
        self._records: list[OnlyAppliedTradeFact] = []
        self._trade_ids: set[OnlyTradeId] = set()

    def append(self, trade: OnlyAppliedTradeFact) -> None:
        if trade.trade_id in self._trade_ids:
            return
        self._trade_ids.add(trade.trade_id)
        self._records.append(trade)

    def records(self) -> tuple[OnlyAppliedTradeFact, ...]:
        return tuple(self._records)

    def __len__(self) -> int:
        return len(self._records)


__all__ = ["OnlyAppliedTradeFact", "OnlyAppliedTradeJournal"]
