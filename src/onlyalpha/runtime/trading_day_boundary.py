"""Shared Runtime trading-day boundary orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby

from onlyalpha.account.manager import OnlyAccountManager
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.position.allocation_manager import OnlyPositionAllocationManager
from onlyalpha.position.manager import OnlyPositionManager
from onlyalpha.settlement.authority import OnlySettlementAuthority
from onlyalpha.settlement.identifiers import OnlySettlementInstructionId
from onlyalpha.settlement.models import OnlySettlementDueTransition
from onlyalpha.settlement.planner import (
    OnlySettlementMaturityPlanner,
    OnlySettlementMaturityPlanningContext,
)
from onlyalpha.transaction.coordinator import (
    OnlyRuntimeTransactionCoordinationResult,
    OnlyRuntimeTransactionCoordinationStatus,
    OnlyRuntimeTransactionCoordinator,
)


@dataclass(frozen=True, slots=True)
class OnlyTradingDayBoundaryResult:
    previous_day: OnlyTradingDay
    current_day: OnlyTradingDay
    maturities: tuple[OnlyRuntimeTransactionCoordinationResult, ...]


class OnlyRuntimeTradingDayBoundaryCoordinator:
    def __init__(
        self,
        *,
        settlement_authority: OnlySettlementAuthority,
        position_manager: OnlyPositionManager,
        allocation_manager: OnlyPositionAllocationManager,
        account_manager: OnlyAccountManager,
        transaction_coordinator: OnlyRuntimeTransactionCoordinator,
        maturity_planner: OnlySettlementMaturityPlanner | None = None,
    ) -> None:
        self._settlements = settlement_authority
        self._positions = position_manager
        self._allocations = allocation_manager
        self._accounts = account_manager
        self._transactions = transaction_coordinator
        self._planner = maturity_planner or OnlySettlementMaturityPlanner()

    def process_boundary(
        self,
        previous_day: OnlyTradingDay,
        current_day: OnlyTradingDay,
        timestamp: OnlyTimestamp,
    ) -> OnlyTradingDayBoundaryResult:
        if current_day <= previous_day:
            raise ValueError("Trading-day boundary must advance")
        due = self._settlements.due_transitions(current_day)
        results: list[OnlyRuntimeTransactionCoordinationResult] = []

        def key(item: OnlySettlementDueTransition) -> tuple[OnlyTradingDay, OnlySettlementInstructionId]:
            return item.effective_on, item.instruction_id

        for (effective_on, instruction_id), grouped in groupby(due, key=key):
            transitions = tuple(item.transition for item in grouped)
            authority = self._settlements.require(instruction_id)
            instruction = authority.instruction
            position = next(
                (
                    item
                    for item in (*self._positions.snapshot_all(), *self._positions.closed())
                    if item.position_id == instruction.position_id
                ),
                None,
            )
            allocation = next(
                (
                    item
                    for item in (*self._allocations.snapshot_all(), *self._allocations.closed())
                    if item.allocation_id == instruction.allocation_id
                ),
                None,
            )
            if position is None or allocation is None:
                raise RuntimeError("SETTLEMENT_LIFECYCLE_AUTHORITY_MISSING")
            prepared = self._planner.prepare(
                OnlySettlementMaturityPlanningContext(
                    authority,
                    position,
                    self._positions.creation_cycle_head(position.key),
                    allocation,
                    self._allocations.creation_cycle_head(allocation.key),
                    self._accounts.require_snapshot(instruction.account_id),
                    effective_on,
                    timestamp,
                    transitions,
                )
            )
            result = self._transactions.commit(prepared, committed_at=timestamp, projected_at=timestamp)
            results.append(result)
            if result.status not in {
                OnlyRuntimeTransactionCoordinationStatus.COMMITTED_AND_PROJECTED,
                OnlyRuntimeTransactionCoordinationStatus.ALREADY_READY,
            }:
                raise RuntimeError(f"SETTLEMENT_MATURITY_FAILED: {result.status.value}: {result.error}")
        return OnlyTradingDayBoundaryResult(previous_day, current_day, tuple(results))


__all__ = ["OnlyRuntimeTradingDayBoundaryCoordinator", "OnlyTradingDayBoundaryResult"]
