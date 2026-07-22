"""Cluster-scoped immutable Strategy Ledger views."""

from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyRate
from onlyalpha.strategy_ledger.enums import OnlyStrategyLedgerStatus
from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey
from onlyalpha.strategy_ledger.locator import OnlyStrategyLedgerLocator
from onlyalpha.strategy_ledger.models import (
    OnlyStrategyLedgerRiskSnapshot,
    OnlyStrategyLedgerSnapshot,
)
from onlyalpha.strategy_ledger.query import OnlyStrategyLedgerQueryService


class OnlyStrategyLedgerContextView:
    """Read-only facade; intentionally exposes no command methods."""

    __slots__ = ("__key", "__query")

    def __init__(self, key: OnlyStrategyLedgerKey, query: OnlyStrategyLedgerQueryService) -> None:
        self.__key = key
        self.__query = query

    def snapshot(self) -> OnlyStrategyLedgerSnapshot:
        return self.__query.require(self.__key)

    @property
    def equity(self) -> OnlyMoney:
        return self.snapshot().equity.equity

    @property
    def cash_balance(self) -> OnlyMoney:
        return self.snapshot().cash.cash_balance

    @property
    def cash_available(self) -> OnlyMoney:
        return self.snapshot().cash.cash_available

    @property
    def cash_reserved(self) -> OnlyMoney:
        return self.snapshot().cash.cash_reserved

    @property
    def realized_pnl(self) -> OnlyMoney:
        return self.snapshot().pnl.realized_pnl

    @property
    def unrealized_pnl(self) -> OnlyMoney:
        return self.snapshot().pnl.unrealized_pnl

    @property
    def net_pnl(self) -> OnlyMoney:
        return self.snapshot().pnl.net_pnl

    @property
    def fees(self) -> OnlyMoney:
        return self.snapshot().pnl.fees

    @property
    def return_since_start(self) -> OnlyRate | None:
        return self.snapshot().equity.return_since_start

    @property
    def drawdown(self) -> OnlyRate:
        return self.snapshot().equity.drawdown

    @property
    def maximum_drawdown(self) -> OnlyRate:
        return self.snapshot().equity.maximum_drawdown


class OnlyStrategyLedgerRiskView:
    """Risk-facing view with explicit fail-closed status semantics."""

    def __init__(
        self,
        query: OnlyStrategyLedgerQueryService,
        locator: OnlyStrategyLedgerLocator,
        base_currency: OnlyCurrency,
    ) -> None:
        self.__query = query
        self.__locator = locator
        self.__base_currency = base_currency

    @property
    def available(self) -> bool:
        return True

    def snapshot(self, account_id: OnlyAccountId, cluster_id: OnlyClusterId) -> OnlyStrategyLedgerRiskSnapshot:
        key = self.__locator.require_key(
            runtime_id=self.__query.runtime_id,
            account_id=account_id,
            cluster_id=cluster_id,
            currency=self.__base_currency,
        )
        item = self.__query.require(key)
        return OnlyStrategyLedgerRiskSnapshot(
            key,
            item.status,
            item.updated_at,
            item.version,
            item.equity.equity,
            item.cash.cash_available,
            item.cash.cash_reserved,
            item.pnl.net_pnl,
            item.equity.daily_pnl,
            item.equity.drawdown,
            item.equity.maximum_drawdown,
        )

    def allows_new_orders(self, account_id: OnlyAccountId, cluster_id: OnlyClusterId) -> bool:
        return self.snapshot(account_id, cluster_id).status is OnlyStrategyLedgerStatus.ACTIVE
