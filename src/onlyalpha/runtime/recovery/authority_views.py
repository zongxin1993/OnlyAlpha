"""Narrow read-only authority views consumed by post-recovery validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.broker.ports import OnlyBrokerGateway
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyOrderId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.runtime.checkpoint.model import OnlyBacktestReplayCursor


@dataclass(frozen=True, slots=True)
class OnlyBrokerRecoveryOrderSnapshot:
    order_id: OnlyOrderId
    account_id: OnlyAccountId
    instrument_id: str
    side: str
    status: str
    quantity: OnlyQuantity
    filled_quantity: OnlyQuantity
    remaining_quantity: OnlyQuantity
    limit_price: OnlyPrice | None
    broker_sequence: int | None = None


class OnlyBrokerRecoveryAuthorityView(Protocol):
    def orders(self) -> tuple[OnlyBrokerRecoveryOrderSnapshot, ...]: ...


class OnlyGatewayBrokerRecoveryAuthorityView:
    def __init__(self, gateway: OnlyBrokerGateway, account_ids: tuple[OnlyAccountId, ...]) -> None:
        self._gateway = gateway
        self._account_ids = account_ids

    def orders(self) -> tuple[OnlyBrokerRecoveryOrderSnapshot, ...]:
        snapshots = tuple(item for account_id in self._account_ids for item in self._gateway.query_orders(account_id))
        return tuple(
            OnlyBrokerRecoveryOrderSnapshot(
                item.order_id,
                item.account_id,
                str(item.instrument_id),
                item.side.value,
                item.status.value,
                item.quantity,
                item.filled_quantity,
                item.remaining_quantity,
                item.price,
                item.source_sequence,
            )
            for item in sorted(snapshots, key=lambda value: str(value.order_id))
        )


@dataclass(frozen=True, slots=True)
class OnlyRuntimeBoundaryAuthorityView:
    runtime_id: OnlyRuntimeId
    broker_inbound_count: int
    market_data_inbound_count: int
    event_bus_pending_count: int
    replay_cursor: OnlyBacktestReplayCursor
    processed_bar_count: int
    last_market_processing_sequence: int
    market_processing_sequence: int
    clock_time: OnlyTimestamp

    def __post_init__(self) -> None:
        if (
            min(
                self.broker_inbound_count,
                self.market_data_inbound_count,
                self.event_bus_pending_count,
                self.processed_bar_count,
                self.last_market_processing_sequence,
                self.market_processing_sequence,
            )
            < 0
        ):
            raise ValueError("runtime boundary counters cannot be negative")


__all__ = [
    "OnlyBrokerRecoveryAuthorityView",
    "OnlyBrokerRecoveryOrderSnapshot",
    "OnlyGatewayBrokerRecoveryAuthorityView",
    "OnlyRuntimeBoundaryAuthorityView",
]
