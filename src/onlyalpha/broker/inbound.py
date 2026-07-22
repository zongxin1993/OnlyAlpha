"""Runtime-owned deterministic Broker inbound queue."""

from __future__ import annotations

from collections import deque
from enum import StrEnum
from typing import Protocol

from onlyalpha.broker.updates import OnlyBrokerInboundUpdate


class OnlyBrokerInboundOverflowPolicy(StrEnum):
    """Explicit behavior when the bounded queue is full."""

    REJECT = "REJECT"


class OnlyBrokerInboundQueue(Protocol):
    def put(self, update: OnlyBrokerInboundUpdate) -> None: ...

    def drain(self) -> tuple[OnlyBrokerInboundUpdate, ...]: ...

    def __len__(self) -> int: ...


class OnlyBrokerInboundQueueFullError(RuntimeError):
    pass


class OnlyBoundedBrokerInboundQueue:
    """FIFO queue with a fixed capacity and fail-closed overflow semantics."""

    def __init__(
        self,
        capacity: int = 1024,
        overflow_policy: OnlyBrokerInboundOverflowPolicy = OnlyBrokerInboundOverflowPolicy.REJECT,
    ) -> None:
        if capacity <= 0:
            raise ValueError("Broker inbound queue capacity must be positive")
        self._capacity = capacity
        self._overflow_policy = overflow_policy
        self._updates: deque[OnlyBrokerInboundUpdate] = deque()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def overflow_policy(self) -> OnlyBrokerInboundOverflowPolicy:
        return self._overflow_policy

    def put(self, update: OnlyBrokerInboundUpdate) -> None:
        if len(self._updates) >= self._capacity:
            raise OnlyBrokerInboundQueueFullError("Broker inbound queue capacity exceeded")
        self._updates.append(update)

    def drain(self) -> tuple[OnlyBrokerInboundUpdate, ...]:
        updates = tuple(self._updates)
        self._updates.clear()
        return updates

    def __len__(self) -> int:
        return len(self._updates)


__all__ = [
    "OnlyBoundedBrokerInboundQueue",
    "OnlyBrokerInboundOverflowPolicy",
    "OnlyBrokerInboundQueue",
    "OnlyBrokerInboundQueueFullError",
]
