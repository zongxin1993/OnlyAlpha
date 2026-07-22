"""Read-only Strategy Ledger query service."""

from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey
from onlyalpha.strategy_ledger.manager import OnlyStrategyLedgerManager
from onlyalpha.strategy_ledger.models import OnlyStrategyLedgerSnapshot


class OnlyStrategyLedgerQueryService:
    def __init__(self, manager: OnlyStrategyLedgerManager) -> None:
        self.__manager = manager

    @property
    def runtime_id(self) -> OnlyRuntimeId:
        return self.__manager.runtime_id

    def get(self, key: OnlyStrategyLedgerKey) -> OnlyStrategyLedgerSnapshot | None:
        return self.__manager.get_snapshot(key)

    def require(self, key: OnlyStrategyLedgerKey) -> OnlyStrategyLedgerSnapshot:
        return self.__manager.require_snapshot(key)

    def all(self) -> tuple[OnlyStrategyLedgerSnapshot, ...]:
        return self.__manager.list_ledgers()
