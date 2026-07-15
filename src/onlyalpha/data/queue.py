"""Runtime-owned bounded market-data inbound queue."""

from collections import deque

from onlyalpha.data.enums import OnlyMarketDataBackpressurePolicy
from onlyalpha.data.models import OnlyMarketDataInboundUpdate


class OnlyMarketDataQueueFullError(RuntimeError):
    pass


class OnlyMarketDataInboundQueue:
    def __init__(
        self,
        capacity: int,
        policy: OnlyMarketDataBackpressurePolicy = OnlyMarketDataBackpressurePolicy.REJECT_NEW,
    ) -> None:
        if capacity <= 0:
            raise ValueError("market-data queue capacity must be positive")
        if policy not in (OnlyMarketDataBackpressurePolicy.REJECT_NEW, OnlyMarketDataBackpressurePolicy.FAIL_RUNTIME):
            raise ValueError("first-phase queue only supports lossless reject/fail policies")
        self._capacity = capacity
        self._policy = policy
        self._items: deque[OnlyMarketDataInboundUpdate] = deque()

    def put(self, update: OnlyMarketDataInboundUpdate) -> None:
        if len(self._items) >= self._capacity:
            raise OnlyMarketDataQueueFullError("market-data inbound queue is full; no data was dropped")
        self._items.append(update)

    def get(self) -> OnlyMarketDataInboundUpdate | None:
        return self._items.popleft() if self._items else None

    def __len__(self) -> int:
        return len(self._items)
