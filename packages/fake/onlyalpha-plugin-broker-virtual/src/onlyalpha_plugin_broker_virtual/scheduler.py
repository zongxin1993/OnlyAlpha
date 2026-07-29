"""Deterministic due-time scheduler for the virtual Broker."""

from __future__ import annotations

import heapq
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol


class OnlyVirtualBrokerScheduledActionResolver(Protocol):
    def __call__(self, payload: object) -> Callable[[], None]: ...


@dataclass(order=True, slots=True)
class _OnlyScheduledAction:
    due_ns: int
    sequence: int
    action: Callable[[], None] = field(compare=False)
    checkpoint_payload: object = field(compare=False)


class OnlyVirtualBrokerScheduler:
    def __init__(self) -> None:
        self._actions: list[_OnlyScheduledAction] = []
        self._sequence = 0

    def schedule(self, due_ns: int, action: Callable[[], None], *, checkpoint_payload: object) -> None:
        self._sequence += 1
        heapq.heappush(
            self._actions,
            _OnlyScheduledAction(due_ns, self._sequence, action, checkpoint_payload),
        )

    def run_due(self, now_ns: int) -> int:
        count = 0
        while self._actions and self._actions[0].due_ns <= now_ns:
            heapq.heappop(self._actions).action()
            count += 1
        return count

    def __len__(self) -> int:
        return len(self._actions)

    def capture_checkpoint(self) -> object:
        return {
            "actions": [
                {
                    "due_ns": item.due_ns,
                    "payload": item.checkpoint_payload,
                    "sequence": item.sequence,
                }
                for item in sorted(self._actions)
            ],
            "sequence": self._sequence,
        }

    def restore_checkpoint(self, payload: object, resolver: OnlyVirtualBrokerScheduledActionResolver) -> None:
        if not isinstance(payload, dict):
            raise ValueError("Virtual Broker scheduler checkpoint must be an object")
        actions: list[_OnlyScheduledAction] = []
        for item in payload["actions"]:
            if not isinstance(item, dict):
                raise ValueError("Virtual Broker scheduled action must be an object")
            action_payload = item["payload"]
            actions.append(
                _OnlyScheduledAction(
                    int(item["due_ns"]),
                    int(item["sequence"]),
                    resolver(action_payload),
                    action_payload,
                )
            )
        self._actions = actions
        heapq.heapify(self._actions)
        self._sequence = int(payload["sequence"])
