"""Deterministic long-only FIFO reconstruction from Execution facts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from onlyalpha.analytics.models import OnlyTradeRecord
from onlyalpha.result.records import OnlyExecutionResultRecord


class OnlyTradeMatchingPolicy(StrEnum):
    FIFO = "FIFO"


@dataclass(slots=True)
class _OnlyOpenLot:
    execution: OnlyExecutionResultRecord
    remaining_quantity: Decimal
    remaining_commission: Decimal
    remaining_fees: Decimal


@dataclass(frozen=True, slots=True)
class OnlyTradeBuildResult:
    trades: tuple[OnlyTradeRecord, ...]
    warnings: tuple[str, ...]


class OnlyTradeBuilder:
    def build(
        self,
        executions: tuple[OnlyExecutionResultRecord, ...],
        policy: OnlyTradeMatchingPolicy = OnlyTradeMatchingPolicy.FIFO,
    ) -> OnlyTradeBuildResult:
        if policy is not OnlyTradeMatchingPolicy.FIFO:
            raise ValueError(f"unsupported trade matching policy: {policy}")
        lots: dict[tuple[str, str, str, str, str], list[_OnlyOpenLot]] = {}
        trades: list[OnlyTradeRecord] = []
        warnings: list[str] = []
        for execution in sorted(executions, key=lambda item: item.sequence):
            key = (
                execution.cluster_id,
                execution.strategy_id,
                execution.account_id,
                execution.instrument_id,
                execution.position_side or "UNKNOWN",
            )
            if execution.position_effect == "OPEN":
                lots.setdefault(key, []).append(
                    _OnlyOpenLot(
                        execution,
                        execution.quantity,
                        execution.commission,
                        execution.fees,
                    )
                )
                continue
            if execution.position_effect not in {"CLOSE", "CLOSE_TODAY", "CLOSE_YESTERDAY"}:
                warnings.append(f"UNSUPPORTED_EXECUTION:{execution.execution_id}")
                continue
            remaining_exit = execution.quantity
            remaining_exit_commission = execution.commission
            remaining_exit_fees = execution.fees
            queue = lots.setdefault(key, [])
            while remaining_exit > 0 and queue:
                lot = queue[0]
                matched = min(remaining_exit, lot.remaining_quantity)
                entry_commission = self._allocate(lot.remaining_commission, matched, lot.remaining_quantity)
                entry_fees = self._allocate(lot.remaining_fees, matched, lot.remaining_quantity)
                exit_commission = self._allocate(remaining_exit_commission, matched, remaining_exit)
                exit_fees = self._allocate(remaining_exit_fees, matched, remaining_exit)
                price_delta = (
                    execution.price - lot.execution.price
                    if execution.position_side == "LONG"
                    else lot.execution.price - execution.price
                )
                gross_pnl = price_delta * matched * execution.contract_multiplier
                commission = entry_commission + exit_commission
                fees = entry_fees + exit_fees
                trades.append(
                    OnlyTradeRecord(
                        trade_id=f"TRADE-{len(trades) + 1:012d}",
                        cluster_id=execution.cluster_id,
                        strategy_id=execution.strategy_id,
                        account_id=execution.account_id,
                        instrument_id=execution.instrument_id,
                        direction=execution.position_side or "UNKNOWN",
                        quantity=matched,
                        entry_time=lot.execution.ts_event,
                        exit_time=execution.ts_event,
                        entry_price=lot.execution.price,
                        exit_price=execution.price,
                        gross_pnl=gross_pnl,
                        commission=commission,
                        fees=fees,
                        net_pnl=gross_pnl - fees,
                        holding_duration=execution.ts_event - lot.execution.ts_event,
                        entry_execution_id=lot.execution.execution_id,
                        exit_execution_id=execution.execution_id,
                        entry_order_id=lot.execution.order_id,
                        exit_order_id=execution.order_id,
                    )
                )
                lot.remaining_quantity -= matched
                lot.remaining_commission -= entry_commission
                lot.remaining_fees -= entry_fees
                remaining_exit -= matched
                remaining_exit_commission -= exit_commission
                remaining_exit_fees -= exit_fees
                if lot.remaining_quantity == 0:
                    queue.pop(0)
            if remaining_exit > 0:
                warnings.append(f"UNMATCHED_CLOSE:{execution.execution_id}:{remaining_exit}")
        for queue in lots.values():
            for lot in queue:
                if lot.remaining_quantity > 0:
                    warnings.append(f"OPEN_LOT_REMAINS:{lot.execution.execution_id}:{lot.remaining_quantity}")
        return OnlyTradeBuildResult(tuple(trades), tuple(sorted(warnings)))

    @staticmethod
    def _allocate(total: Decimal, quantity: Decimal, remaining_quantity: Decimal) -> Decimal:
        if quantity == remaining_quantity:
            return total
        return total * quantity / remaining_quantity
