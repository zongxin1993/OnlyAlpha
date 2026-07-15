"""First-phase deterministic in-memory Position repositories."""

from onlyalpha.position.models import OnlyPositionAllocationSnapshot, OnlyPositionSnapshot


class OnlyInMemoryPositionRepository:
    def __init__(self) -> None:
        self._items: dict[object, OnlyPositionSnapshot] = {}

    def save(self, snapshot: OnlyPositionSnapshot) -> None:
        self._items[snapshot.position_id] = snapshot

    def snapshots(self) -> tuple[OnlyPositionSnapshot, ...]:
        return tuple(sorted(self._items.values(), key=lambda item: str(item.position_id)))


class OnlyInMemoryPositionAllocationRepository:
    def __init__(self) -> None:
        self._items: dict[object, OnlyPositionAllocationSnapshot] = {}

    def save(self, snapshot: OnlyPositionAllocationSnapshot) -> None:
        self._items[snapshot.allocation_id] = snapshot

    def snapshots(self) -> tuple[OnlyPositionAllocationSnapshot, ...]:
        return tuple(sorted(self._items.values(), key=lambda item: str(item.allocation_id)))
