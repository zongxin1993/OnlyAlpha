"""Deterministic due-time scheduler for the virtual Broker."""

from __future__ import annotations

import heapq
from collections.abc import Callable
from dataclasses import dataclass, field


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
