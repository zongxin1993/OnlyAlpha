"""Exact Strategy Ledger lookup by complete business scope."""

from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyRuntimeId
from onlyalpha.domain.value import OnlyCurrency
from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey
from onlyalpha.strategy_ledger.manager import OnlyStrategyLedgerManager
from onlyalpha.strategy_ledger.models import OnlyStrategyLedgerSnapshot


class OnlyStrategyLedgerLocator:
    def __init__(self, manager: OnlyStrategyLedgerManager) -> None:
        self._manager = manager

    def require_key(
        self,
        *,
        runtime_id: OnlyRuntimeId,
        account_id: OnlyAccountId,
        cluster_id: OnlyClusterId,
        currency: OnlyCurrency,
    ) -> OnlyStrategyLedgerKey:
        return self._manager.require_key(
            runtime_id=runtime_id,
            account_id=account_id,
            cluster_id=cluster_id,
            currency=currency,
        )

    def require_snapshot(
        self,
        *,
        runtime_id: OnlyRuntimeId,
        account_id: OnlyAccountId,
        cluster_id: OnlyClusterId,
        currency: OnlyCurrency,
    ) -> OnlyStrategyLedgerSnapshot:
        return self._manager.require_snapshot_by_scope(
            runtime_id=runtime_id,
            account_id=account_id,
            cluster_id=cluster_id,
            currency=currency,
        )
