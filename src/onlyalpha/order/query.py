"""Snapshot-only Runtime Order queries."""

from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClientOrderId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyVenueOrderId,
)
from onlyalpha.order.manager import OnlyOrderManager


class OnlyOrderQueryService:
    def __init__(self, manager: OnlyOrderManager) -> None:
        self._manager = manager

    def get(self, order_id: OnlyOrderId) -> OnlyOrderSnapshot | None:
        return self._manager.get_snapshot(order_id)

    def require(self, order_id: OnlyOrderId) -> OnlyOrderSnapshot:
        return self._manager.require_snapshot(order_id)

    def find_by_client_order_id(self, client_order_id: OnlyClientOrderId) -> OnlyOrderSnapshot | None:
        return self._manager.find_by_client_order_id(client_order_id)

    def find_by_venue_order_id(self, venue_order_id: OnlyVenueOrderId) -> OnlyOrderSnapshot | None:
        return self._manager.find_by_venue_order_id(venue_order_id)

    def list_open(self) -> tuple[OnlyOrderSnapshot, ...]:
        return self._manager.list_open_orders()

    def list_by_cluster(self, cluster_id: OnlyClusterId) -> tuple[OnlyOrderSnapshot, ...]:
        return self._manager.list_by_cluster(cluster_id)

    def list_by_account(self, account_id: OnlyAccountId) -> tuple[OnlyOrderSnapshot, ...]:
        return self._manager.list_by_account(account_id)

    def list_by_instrument(self, instrument_id: OnlyInstrumentId) -> tuple[OnlyOrderSnapshot, ...]:
        return self._manager.list_by_instrument(instrument_id)

    def list_recent(self, limit: int = 100) -> tuple[OnlyOrderSnapshot, ...]:
        return self._manager.list_recent(limit)
