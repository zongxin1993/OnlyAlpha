"""Read-only Risk data and strategy Snapshot views."""

from collections.abc import Callable, Mapping
from types import MappingProxyType

from onlyalpha.account.enums import OnlyAccountStatus
from onlyalpha.account.views import OnlyAccountQueryService
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyInstrumentId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.order.query import OnlyOrderQueryService
from onlyalpha.risk.enums import OnlyRiskLevel
from onlyalpha.risk.ports import OnlyAccountRiskSnapshot
from onlyalpha.risk.snapshots import OnlyRiskSnapshot


class OnlyInstrumentRiskMappingView:
    def __init__(self, instruments: Mapping[OnlyInstrumentId, OnlyInstrument]) -> None:
        self._instruments = MappingProxyType(instruments)

    def get(self, instrument_id: OnlyInstrumentId) -> OnlyInstrument | None:
        return self._instruments.get(instrument_id)


class OnlyOrderRiskQueryView:
    def __init__(self, query: OnlyOrderQueryService) -> None:
        self._query = query

    def active_count(
        self,
        *,
        cluster_id: OnlyClusterId | None = None,
        account_id: OnlyAccountId | None = None,
        instrument_id: OnlyInstrumentId | None = None,
    ) -> int:
        items = self._query.list_open()
        return sum(
            (cluster_id is None or item.cluster_id == cluster_id)
            and (account_id is None or item.account_id == account_id)
            and (instrument_id is None or item.instrument_id == instrument_id)
            for item in items
        )


class OnlyClusterPermissionMappingView:
    def __init__(self) -> None:
        self._clusters: dict[OnlyClusterId, tuple[frozenset[OnlyAccountId], frozenset[OnlyInstrumentId]]] = {}

    def bind(
        self,
        cluster_id: OnlyClusterId,
        account_ids: frozenset[OnlyAccountId],
        instrument_ids: frozenset[OnlyInstrumentId],
    ) -> None:
        self._clusters[cluster_id] = (account_ids, instrument_ids)

    def unbind(self, cluster_id: OnlyClusterId) -> None:
        self._clusters.pop(cluster_id, None)

    def cluster_is_authorized(self, cluster_id: OnlyClusterId) -> bool:
        return cluster_id in self._clusters

    def account_is_authorized(self, cluster_id: OnlyClusterId, account_id: OnlyAccountId) -> bool:
        entry = self._clusters.get(cluster_id)
        return entry is not None and (not entry[0] or account_id in entry[0])

    def instrument_is_authorized(self, cluster_id: OnlyClusterId, instrument_id: OnlyInstrumentId) -> bool:
        entry = self._clusters.get(cluster_id)
        return entry is not None and (not entry[1] or instrument_id in entry[1])


class OnlyRiskSnapshotView:
    """Cluster-facing immutable Risk state capability; no evaluation or mutation methods."""

    __slots__ = ("__snapshot",)

    def __init__(self, snapshot: Callable[[], OnlyRiskSnapshot]) -> None:
        self.__snapshot = snapshot

    def snapshot(self) -> OnlyRiskSnapshot:
        return self.__snapshot()

    @property
    def current_level(self) -> OnlyRiskLevel:
        return self.snapshot().risk_level

    @property
    def kill_switch_active(self) -> bool:
        return self.snapshot().kill_switch_active

    @property
    def active_order_count(self) -> int:
        return self.snapshot().active_order_count

    @property
    def reserved_notional(self) -> OnlyMoney | None:
        return self.snapshot().reserved_notional


class OnlyAccountManagerRiskView:
    """Risk-owned adapter over the Account component's immutable query service."""

    def __init__(self, query: OnlyAccountQueryService) -> None:
        self._query = query

    @property
    def available(self) -> bool:
        return True

    def snapshot(self, account_id: OnlyAccountId) -> OnlyAccountRiskSnapshot | None:
        value = self._query.get(account_id)
        if value is None:
            return None
        return OnlyAccountRiskSnapshot(
            value.account_id,
            value.updated_at,
            value.version,
            (value.cash.available_cash,),
            value.status is OnlyAccountStatus.ACTIVE,
            value.status.value,
            value.equity,
            value.quality_flags,
            value.available_margin,
        )
