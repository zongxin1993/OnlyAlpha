"""Read-only data ports used by Risk Rules."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyInstrumentId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyQuantity
from onlyalpha.position.enums import OnlyPositionSide


class OnlyInstrumentRiskView(Protocol):
    def get(self, instrument_id: OnlyInstrumentId) -> OnlyInstrument | None: ...


class OnlyOrderRiskView(Protocol):
    def active_count(
        self,
        *,
        cluster_id: OnlyClusterId | None = None,
        account_id: OnlyAccountId | None = None,
        instrument_id: OnlyInstrumentId | None = None,
    ) -> int: ...


class OnlyRiskReservationView(Protocol):
    def active_notional(
        self,
        currency: OnlyCurrency,
        *,
        cluster_id: OnlyClusterId | None = None,
        account_id: OnlyAccountId | None = None,
        instrument_id: OnlyInstrumentId | None = None,
    ) -> OnlyMoney: ...

    def active_quantity(
        self,
        instrument_id: OnlyInstrumentId,
        *,
        cluster_id: OnlyClusterId | None = None,
        account_id: OnlyAccountId | None = None,
    ) -> Decimal: ...


class OnlyClusterPermissionView(Protocol):
    def cluster_is_authorized(self, cluster_id: OnlyClusterId) -> bool: ...

    def account_is_authorized(self, cluster_id: OnlyClusterId, account_id: OnlyAccountId) -> bool: ...

    def instrument_is_authorized(self, cluster_id: OnlyClusterId, instrument_id: OnlyInstrumentId) -> bool: ...


@dataclass(frozen=True, slots=True)
class OnlyAccountRiskSnapshot(OnlyDomainModel):
    account_id: OnlyAccountId
    as_of: OnlyTimestamp
    version: int
    available_balances: tuple[OnlyMoney, ...]
    allows_new_orders: bool = True
    status: str = "ACTIVE"
    equity: OnlyMoney | None = None
    quality_flags: tuple[str, ...] = ()
    available_margin: OnlyMoney | None = None


@dataclass(frozen=True, slots=True)
class OnlyPositionRiskSnapshot(OnlyDomainModel):
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId
    as_of: OnlyTimestamp
    version: int
    available_quantity: OnlyQuantity


class OnlyAccountRiskView(Protocol):
    @property
    def available(self) -> bool: ...

    def snapshot(self, account_id: OnlyAccountId) -> OnlyAccountRiskSnapshot | None: ...


class OnlyPositionRiskView(Protocol):
    @property
    def available(self) -> bool: ...

    def snapshot(
        self,
        account_id: OnlyAccountId,
        instrument_id: OnlyInstrumentId,
        position_side: OnlyPositionSide = OnlyPositionSide.LONG,
    ) -> OnlyPositionRiskSnapshot | None: ...

    def cluster_snapshot(
        self,
        account_id: OnlyAccountId,
        cluster_id: OnlyClusterId,
        instrument_id: OnlyInstrumentId,
    ) -> OnlyPositionRiskSnapshot | None: ...


class OnlyStrategyLedgerRiskViewPort(Protocol):
    """Boundary port; Risk never owns or mutates a Strategy Ledger."""

    def allows_new_orders(self, account_id: OnlyAccountId, cluster_id: OnlyClusterId) -> bool: ...


class OnlyUnavailableAccountRiskView:
    @property
    def available(self) -> bool:
        return False

    def snapshot(self, account_id: OnlyAccountId) -> OnlyAccountRiskSnapshot | None:
        del account_id
        return None


class OnlyUnavailablePositionRiskView:
    @property
    def available(self) -> bool:
        return False

    def snapshot(
        self,
        account_id: OnlyAccountId,
        instrument_id: OnlyInstrumentId,
        position_side: OnlyPositionSide = OnlyPositionSide.LONG,
    ) -> OnlyPositionRiskSnapshot | None:
        del account_id, instrument_id, position_side
        return None

    def cluster_snapshot(
        self,
        account_id: OnlyAccountId,
        cluster_id: OnlyClusterId,
        instrument_id: OnlyInstrumentId,
    ) -> OnlyPositionRiskSnapshot | None:
        del account_id, cluster_id, instrument_id
        return None
