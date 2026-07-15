"""Trading-day-driven Position settlement orchestration."""

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.domain.identifiers import OnlyAccountId
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.position.allocation_manager import OnlyPositionAllocationManager
from onlyalpha.position.manager import OnlyPositionManager
from onlyalpha.position.models import OnlySettlementResult


class OnlySettlementRule(Protocol):
    def may_settle(self, previous_trading_day: OnlyTradingDay, trading_day: OnlyTradingDay) -> bool: ...


@dataclass(frozen=True, slots=True)
class OnlyT1SettlementRule:
    def may_settle(self, previous_trading_day: OnlyTradingDay, trading_day: OnlyTradingDay) -> bool:
        return trading_day.value > previous_trading_day.value


class OnlySettlementService:
    """Moves Buckets only after a caller supplies a calendar-derived TradingDay."""

    def __init__(
        self,
        positions: OnlyPositionManager,
        allocations: OnlyPositionAllocationManager,
        rule: OnlySettlementRule | None = None,
    ) -> None:
        self._positions = positions
        self._allocations = allocations
        self._rule = rule or OnlyT1SettlementRule()

    def settle_account(
        self,
        account_id: OnlyAccountId,
        previous_trading_day: OnlyTradingDay,
        trading_day: OnlyTradingDay,
    ) -> tuple[OnlySettlementResult, ...]:
        if not self._rule.may_settle(previous_trading_day, trading_day):
            return ()
        results: list[OnlySettlementResult] = []
        for snapshot in self._positions.list_by_account(account_id):
            results.append(self._positions.settle(snapshot.key, trading_day))
        for allocation in self._allocations.list_by_account(account_id):
            results.append(self._allocations.settle(allocation.key, trading_day))
        return tuple(results)
