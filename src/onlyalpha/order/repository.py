"""Order persistence port and isolated in-memory reference implementation."""

from typing import Protocol

from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.identifiers import OnlyClusterId, OnlyOrderId


class OnlyOrderRepository(Protocol):
    def save(self, snapshot: OnlyOrderSnapshot, expected_version: int | None = None) -> None: ...

    def get(self, order_id: OnlyOrderId) -> OnlyOrderSnapshot | None: ...

    def list_by_cluster(self, cluster_id: OnlyClusterId) -> tuple[OnlyOrderSnapshot, ...]: ...


class OnlyInMemoryOrderRepository:
    """Optional persistence port; OnlyOrderManager remains Runtime truth."""

    def __init__(self) -> None:
        self._snapshots: dict[OnlyOrderId, OnlyOrderSnapshot] = {}

    def save(self, snapshot: OnlyOrderSnapshot, expected_version: int | None = None) -> None:
        current = self._snapshots.get(snapshot.order_id)
        if expected_version is not None and (current is None or current.version != expected_version):
            raise ValueError("Order repository optimistic version mismatch")
        self._snapshots[snapshot.order_id] = snapshot

    def get(self, order_id: OnlyOrderId) -> OnlyOrderSnapshot | None:
        return self._snapshots.get(order_id)

    def list_by_cluster(self, cluster_id: OnlyClusterId) -> tuple[OnlyOrderSnapshot, ...]:
        return tuple(item for item in self._snapshots.values() if item.cluster_id == cluster_id)
