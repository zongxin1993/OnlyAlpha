"""Cluster-scoped immutable Position Context and Risk views."""

from collections.abc import Callable

from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyInstrumentId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.position.enums import OnlyPositionMode, OnlyPositionSide
from onlyalpha.position.models import OnlyPositionAllocationSnapshot, OnlyPositionSnapshot
from onlyalpha.position.queries import OnlyPositionQueryService
from onlyalpha.risk.ports import OnlyPositionRiskSnapshot


class OnlyAccountPositionQueryView:
    __slots__ = ("__account_id", "__query")

    def __init__(self, account_id: OnlyAccountId, query: OnlyPositionQueryService) -> None:
        self.__account_id = account_id
        self.__query = query

    def get(
        self,
        instrument_id: OnlyInstrumentId,
        side: OnlyPositionSide = OnlyPositionSide.LONG,
    ) -> OnlyPositionSnapshot | None:
        return self.__query.account(self.__account_id, instrument_id, side)


class OnlyClusterPositionQueryView:
    __slots__ = ("__account_id", "__cluster_id", "__query")

    def __init__(
        self,
        account_id: OnlyAccountId,
        cluster_id: OnlyClusterId,
        query: OnlyPositionQueryService,
    ) -> None:
        self.__account_id = account_id
        self.__cluster_id = cluster_id
        self.__query = query

    def get(
        self,
        instrument_id: OnlyInstrumentId,
        side: OnlyPositionSide = OnlyPositionSide.LONG,
    ) -> OnlyPositionAllocationSnapshot | None:
        return self.__query.cluster(self.__account_id, self.__cluster_id, instrument_id, side)


class OnlyPositionContextView:
    __slots__ = ("account", "cluster")

    def __init__(
        self,
        account_id: OnlyAccountId,
        cluster_id: OnlyClusterId,
        query: OnlyPositionQueryService,
    ) -> None:
        self.account = OnlyAccountPositionQueryView(account_id, query)
        self.cluster = OnlyClusterPositionQueryView(account_id, cluster_id, query)


class OnlyAccountPositionRiskView:
    def __init__(self, query: OnlyPositionQueryService, now: Callable[[], int]) -> None:
        self._query = query
        self._now = now

    @property
    def available(self) -> bool:
        return True

    def snapshot(
        self,
        account_id: OnlyAccountId,
        instrument_id: OnlyInstrumentId,
        position_side: OnlyPositionSide = OnlyPositionSide.LONG,
        position_mode: OnlyPositionMode = OnlyPositionMode.NETTING,
    ) -> OnlyPositionRiskSnapshot | None:
        snapshot = self._query.account(account_id, instrument_id, position_side, position_mode)
        if snapshot is None:
            return None
        return OnlyPositionRiskSnapshot(
            account_id,
            instrument_id,
            OnlyTimestamp.from_unix_nanos(self._now()),
            snapshot.version,
            snapshot.available_quantity,
        )


class OnlyClusterPositionRiskView:
    def __init__(self, query: OnlyPositionQueryService, now: Callable[[], int]) -> None:
        self._query = query
        self._now = now

    @property
    def available(self) -> bool:
        return True

    def snapshot(
        self,
        account_id: OnlyAccountId,
        cluster_id: OnlyClusterId,
        instrument_id: OnlyInstrumentId,
        position_side: OnlyPositionSide = OnlyPositionSide.LONG,
        position_mode: OnlyPositionMode = OnlyPositionMode.NETTING,
    ) -> OnlyPositionRiskSnapshot | None:
        account = self._query.account(account_id, instrument_id, position_side, position_mode)
        allocation = self._query.cluster(account_id, cluster_id, instrument_id, position_side)
        if account is None or allocation is None:
            return None
        effective = allocation.available_quantity
        if account.available_quantity.value < effective.value:
            effective = account.available_quantity
        return OnlyPositionRiskSnapshot(
            account_id,
            instrument_id,
            OnlyTimestamp.from_unix_nanos(self._now()),
            max(account.version, allocation.version),
            effective,
        )


OnlyAccountPositionRiskViewAlias = OnlyAccountPositionRiskView
OnlyClusterPositionRiskViewAlias = OnlyClusterPositionRiskView


class OnlyPositionRiskView:
    """Combined Risk port retaining explicit account and Cluster queries."""

    def __init__(self, query: OnlyPositionQueryService, now: Callable[[], int]) -> None:
        self.account = OnlyAccountPositionRiskView(query, now)
        self.cluster = OnlyClusterPositionRiskView(query, now)

    @property
    def available(self) -> bool:
        return True

    def snapshot(
        self,
        account_id: OnlyAccountId,
        instrument_id: OnlyInstrumentId,
        position_side: OnlyPositionSide = OnlyPositionSide.LONG,
        position_mode: OnlyPositionMode = OnlyPositionMode.NETTING,
    ) -> OnlyPositionRiskSnapshot | None:
        return self.account.snapshot(account_id, instrument_id, position_side, position_mode)

    def cluster_snapshot(
        self,
        account_id: OnlyAccountId,
        cluster_id: OnlyClusterId,
        instrument_id: OnlyInstrumentId,
        position_side: OnlyPositionSide = OnlyPositionSide.LONG,
        position_mode: OnlyPositionMode = OnlyPositionMode.NETTING,
    ) -> OnlyPositionRiskSnapshot | None:
        return self.cluster.snapshot(account_id, cluster_id, instrument_id, position_side, position_mode)


OnlyPositionReservationView = object
