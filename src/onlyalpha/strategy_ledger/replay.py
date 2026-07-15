"""Explicit deterministic Strategy Ledger command replay."""

from onlyalpha.strategy_ledger.enums import OnlyStrategyLedgerReplayOperation
from onlyalpha.strategy_ledger.manager import OnlyStrategyLedgerManager
from onlyalpha.strategy_ledger.models import (
    OnlyStrategyCashReservationCommand,
    OnlyStrategyCashReservationReleaseCommand,
    OnlyStrategyExternalCashFlowCommand,
    OnlyStrategyFeeEntry,
    OnlyStrategyLedgerLifecycleCommand,
    OnlyStrategyLedgerReplayEntry,
    OnlyStrategyTradeAccountingInput,
    OnlyStrategyValuation,
)


class OnlyStrategyLedgerReplayService:
    """Re-executes serialized commands; it never restores mutable entities."""

    def replay(
        self,
        manager: OnlyStrategyLedgerManager,
        entries: tuple[OnlyStrategyLedgerReplayEntry, ...],
    ) -> None:
        ordered = tuple(sorted(entries, key=lambda item: item.sequence))
        if tuple(item.sequence for item in ordered) != tuple(range(1, len(ordered) + 1)):
            raise ValueError("Replay sequence must be unique and contiguous from one")
        for entry in ordered:
            self._apply(manager, entry)

    @staticmethod
    def _apply(manager: OnlyStrategyLedgerManager, entry: OnlyStrategyLedgerReplayEntry) -> None:
        operation = entry.operation
        if operation in {
            OnlyStrategyLedgerReplayOperation.CREATE,
            OnlyStrategyLedgerReplayOperation.ACTIVATE,
            OnlyStrategyLedgerReplayOperation.CLOSE,
        }:
            lifecycle = OnlyStrategyLedgerLifecycleCommand.from_json(entry.payload_json)
            if operation is OnlyStrategyLedgerReplayOperation.CREATE:
                if lifecycle.initial_capital is None:
                    raise ValueError("CREATE replay requires initial capital")
                manager.create_ledger(lifecycle.key, lifecycle.initial_capital, lifecycle.timestamp)
            elif operation is OnlyStrategyLedgerReplayOperation.ACTIVATE:
                manager.activate_ledger(lifecycle.key, lifecycle.timestamp)
            else:
                manager.close_ledger(lifecycle.key, lifecycle.timestamp)
            return
        if operation is OnlyStrategyLedgerReplayOperation.RESERVE_CASH:
            reservation = OnlyStrategyCashReservationCommand.from_json(entry.payload_json)
            manager.reserve_cash(
                reservation.key,
                reservation.order_id,
                reservation.estimated_notional,
                reservation.estimated_fee,
                reservation.timestamp,
            )
            return
        if operation is OnlyStrategyLedgerReplayOperation.RELEASE_CASH:
            release = OnlyStrategyCashReservationReleaseCommand.from_json(entry.payload_json)
            manager.release_cash_reservation(release.key, release.order_id, release.timestamp)
            return
        if operation is OnlyStrategyLedgerReplayOperation.APPLY_TRADE:
            accounting = OnlyStrategyTradeAccountingInput.from_json(entry.payload_json)
            if accounting.position_allocation_after is None and accounting.position_allocation_before is None:
                raise ValueError("Trade replay requires an Allocation boundary")
            ledger_key = next(
                item.key
                for item in manager.list_ledgers()
                if item.key.account_id == accounting.trade.account_id
                and item.key.cluster_id == accounting.trade.cluster_id
            )
            manager.apply_trade_accounting(ledger_key, accounting)
            return
        if operation is OnlyStrategyLedgerReplayOperation.APPLY_FEE:
            fee = OnlyStrategyFeeEntry.from_json(entry.payload_json)
            manager.apply_fee(fee.key, fee)
            return
        if operation is OnlyStrategyLedgerReplayOperation.APPLY_EXTERNAL_CASH_FLOW:
            cash_flow = OnlyStrategyExternalCashFlowCommand.from_json(entry.payload_json)
            manager.apply_external_cash_flow(
                cash_flow.key, cash_flow.cash_flow_id, cash_flow.amount, cash_flow.timestamp
            )
            return
        if operation is OnlyStrategyLedgerReplayOperation.APPLY_VALUATION:
            valuation = OnlyStrategyValuation.from_json(entry.payload_json)
            manager.apply_valuation(valuation)
            return
        raise TypeError(f"unsupported Replay operation: {operation}")
