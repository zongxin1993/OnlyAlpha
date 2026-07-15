"""Bounded inbound queue and deterministic due-time scheduler."""

from __future__ import annotations

import heapq
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from onlyalpha.broker.updates import OnlyBrokerInboundUpdate


class OnlyVirtualBrokerUpdateQueue:
    def __init__(self, capacity: int = 1024) -> None:
        if capacity < 1:
            raise ValueError("Broker update queue capacity must be positive")
        self._capacity = capacity
        self._items: deque[OnlyBrokerInboundUpdate] = deque()

    def put(self, update: OnlyBrokerInboundUpdate) -> None:
        if len(self._items) >= self._capacity:
            raise OverflowError("Runtime Broker inbound queue is full")
        self._items.append(update)

    def drain(self) -> tuple[OnlyBrokerInboundUpdate, ...]:
        result = tuple(self._items)
        self._items.clear()
        return result

    def __len__(self) -> int:
        return len(self._items)


@dataclass(order=True, slots=True)
class _OnlyScheduledAction:
    due_ns: int
    sequence: int
    action: Callable[[], None] = field(compare=False)


class OnlyVirtualBrokerScheduler:
    def __init__(self) -> None:
        self._actions: list[_OnlyScheduledAction] = []
        self._sequence = 0

    def schedule(self, due_ns: int, action: Callable[[], None]) -> None:
        self._sequence += 1
        heapq.heappush(self._actions, _OnlyScheduledAction(due_ns, self._sequence, action))

    def run_due(self, now_ns: int) -> int:
        count = 0
        while self._actions and self._actions[0].due_ns <= now_ns:
            heapq.heappop(self._actions).action()
            count += 1
        return count

    def __len__(self) -> int:
        return len(self._actions)
