"""Runtime-private controlled mutable Strategy Ledger entity."""

from decimal import ROUND_HALF_EVEN, Decimal

from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.identifiers import OnlyOrderId, OnlyTradeId
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyMoney, OnlyRate
from onlyalpha.strategy_ledger.enums import (
    OnlyStrategyCapitalAllocationMode,
    OnlyStrategyCashEntryType,
    OnlyStrategyLedgerStatus,
)
from onlyalpha.strategy_ledger.exceptions import (
    OnlyStrategyLedgerCurrencyError,
    OnlyStrategyLedgerInsufficientCashError,
)
from onlyalpha.strategy_ledger.identifiers import (
    OnlyStrategyCashEntryId,
    OnlyStrategyCashFlowId,
    OnlyStrategyLedgerId,
)
from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey
from onlyalpha.strategy_ledger.models import (
    OnlyStrategyCapitalSnapshot,
    OnlyStrategyCashEntry,
    OnlyStrategyCashReservation,
    OnlyStrategyCashSnapshot,
    OnlyStrategyEquitySnapshot,
    OnlyStrategyFeeEntry,
    OnlyStrategyLedgerSnapshot,
    OnlyStrategyPerformanceSnapshot,
    OnlyStrategyPnLSnapshot,
    OnlyStrategyTradeAccountingInput,
    OnlyStrategyValuation,
    OnlyStrategyValuationLine,
    only_zero_money,
)


class OnlyStrategyLedger:
    """Controlled mutable virtual strategy account; never exposed to a Cluster."""

    def __init__(
        self,
        ledger_id: OnlyStrategyLedgerId,
        key: OnlyStrategyLedgerKey,
        initial_capital: OnlyMoney,
        timestamp: OnlyTimestamp,
    ) -> None:
        if initial_capital.currency != key.base_currency or initial_capital.amount < 0:
            raise OnlyStrategyLedgerCurrencyError("initial capital must be non-negative base currency")
        zero = only_zero_money(key.base_currency)
        self.ledger_id = ledger_id
        self.key = key
        self.status = OnlyStrategyLedgerStatus.CREATED
        self.initial_capital = initial_capital
        self.external_cash_flow = zero
        self.cash_balance = initial_capital
        self.realized_pnl = zero
        self.fees = zero
        self._valuation_lines: dict[object, OnlyStrategyValuationLine] = {}
        self.position_cost = zero
        self.position_market_value = zero
        self.unrealized_pnl = zero
        self._equity = initial_capital
        self.high_water_mark = initial_capital
        self.maximum_drawdown = OnlyRate(Decimal(0), 8)
        self.created_at = timestamp
        self.updated_at = timestamp
        self.valuation_time = timestamp
        self.version = 1
        self.last_trade_sequence: int | None = None
        self.last_trade_order: tuple[int, int, str] | None = None
        self.quality_flags: tuple[str, ...] = ()
        self.cash_entries: list[OnlyStrategyCashEntry] = []
        self.fee_entries: list[OnlyStrategyFeeEntry] = []
        self.trade_count = 0
        self.realized_pnl_delta_count = 0
        self.winning_trade_count = 0
        self.losing_trade_count = 0
        self.gross_profit = zero
        self.gross_loss = zero
        self.trading_day: OnlyTradingDay | None = None
        self.day_start_equity = initial_capital
        self._entry_sequence = 0
        self._record_cash(
            OnlyStrategyCashEntryType.INITIAL_ALLOCATION,
            initial_capital,
            timestamp,
            timestamp,
        )

    def activate(self, timestamp: OnlyTimestamp) -> bool:
        if self.status is OnlyStrategyLedgerStatus.ACTIVE:
            return False
        if self.status is not OnlyStrategyLedgerStatus.CREATED:
            raise ValueError("only CREATED Strategy Ledger can activate")
        self.status = OnlyStrategyLedgerStatus.ACTIVE
        self.updated_at = timestamp
        self.version += 1
        return True

    def close(self, timestamp: OnlyTimestamp) -> bool:
        if self.status is OnlyStrategyLedgerStatus.CLOSED:
            return False
        self.status = OnlyStrategyLedgerStatus.CLOSED
        self.updated_at = timestamp
        self.version += 1
        return True

    def snapshot(
        self,
        cash_reserved: OnlyMoney,
        reservations: tuple[OnlyStrategyCashReservation, ...],
    ) -> OnlyStrategyLedgerSnapshot:
        self._require_currency(cash_reserved)
        cash_available = OnlyMoney(self.cash_balance.amount - cash_reserved.amount, self.key.base_currency)
        if cash_available.amount < 0:
            raise OnlyStrategyLedgerInsufficientCashError("Strategy cash available became negative")
        net_pnl = self.realized_pnl + self.unrealized_pnl - self.fees
        cash_view = self.cash_balance + self.position_market_value
        pnl_view = self.initial_capital + self.external_cash_flow + net_pnl
        drawdown = self._drawdown(self._equity)
        simple_return = self._simple_return(self._equity)
        daily_pnl = self._equity - self.day_start_equity
        daily_return = self._daily_return(daily_pnl)
        cash = OnlyStrategyCashSnapshot(self.cash_balance, cash_reserved, cash_available)
        pnl = OnlyStrategyPnLSnapshot(self.realized_pnl, self.unrealized_pnl, self.fees, net_pnl)
        equity = OnlyStrategyEquitySnapshot(
            self.key,
            self.updated_at,
            self.updated_at,
            self.trading_day,
            self.version,
            self.initial_capital,
            self.external_cash_flow,
            self.cash_balance,
            cash_reserved,
            cash_available,
            self.position_cost,
            self.position_market_value,
            self.realized_pnl,
            self.unrealized_pnl,
            self.fees,
            net_pnl,
            self._equity,
            cash_view,
            pnl_view,
            self.high_water_mark,
            drawdown,
            self.maximum_drawdown,
            simple_return,
            daily_pnl,
            daily_return,
            self.quality_flags,
        )
        performance = OnlyStrategyPerformanceSnapshot(
            self.key.cluster_id,
            self.updated_at,
            self._equity,
            net_pnl,
            simple_return,
            daily_pnl,
            daily_return,
            drawdown,
            self.maximum_drawdown,
            self.trade_count,
            self.realized_pnl_delta_count,
            self.winning_trade_count,
            self.losing_trade_count,
            self._win_rate(),
            self.gross_profit,
            self.gross_loss,
            self._profit_factor(),
            self.fees,
        )
        capital = OnlyStrategyCapitalSnapshot(
            self.key,
            OnlyStrategyCapitalAllocationMode.FIXED_CAPITAL,
            self.initial_capital,
            self.external_cash_flow,
            self.updated_at,
            self.version,
        )
        return OnlyStrategyLedgerSnapshot(
            self.ledger_id,
            self.key,
            self.status,
            capital,
            cash,
            pnl,
            equity,
            performance,
            tuple(self.cash_entries),
            tuple(self.fee_entries),
            reservations,
            self.created_at,
            self.updated_at,
            self.valuation_time,
            self.version,
            self.last_trade_sequence,
            self.last_trade_order,
            self.quality_flags,
        )

    def apply_trade(self, accounting: OnlyStrategyTradeAccountingInput) -> tuple[OnlyMoney, OnlyMoney, OnlyMoney]:
        self._require_active()
        trade = accounting.trade
        if trade.runtime_id != self.key.runtime_id or trade.account_id != self.key.account_id:
            raise ValueError("Trade Accounting belongs to another Ledger scope")
        if trade.cluster_id != self.key.cluster_id:
            raise ValueError("Trade Accounting belongs to another Cluster")
        self._require_currency(trade.fee)
        self._require_currency(accounting.realized_pnl_delta)
        self._require_currency(accounting.position_cost_delta)
        fee_total = only_zero_money(self.key.base_currency)
        for entry in accounting.fee_entries:
            self._require_currency(entry.amount)
            fee_total = fee_total + entry.amount
        if fee_total != trade.fee:
            raise ValueError("Fee Entries must sum exactly to Trade fee")
        expected_realized = self._allocation_realized_delta(accounting)
        if expected_realized != accounting.realized_pnl_delta:
            raise ValueError("realized PnL delta must come from Position Allocation")
        if self._allocation_cost_delta(accounting) != accounting.position_cost_delta:
            raise ValueError("position cost delta must come from Position Allocation")
        notional = self._notional(accounting)
        if trade.side is OnlyOrderSide.BUY:
            cash_delta = OnlyMoney(-(notional.amount + trade.fee.amount), self.key.base_currency)
        else:
            cash_delta = OnlyMoney(notional.amount - trade.fee.amount, self.key.base_currency)
        if self.cash_balance.amount + cash_delta.amount < 0:
            raise OnlyStrategyLedgerInsufficientCashError("Trade would make Strategy cash negative")
        self.cash_balance = self.cash_balance + cash_delta
        self.realized_pnl = self.realized_pnl + accounting.realized_pnl_delta
        self.fees = self.fees + trade.fee
        self._update_trade_valuation(accounting)
        self.fee_entries.extend(accounting.fee_entries)
        settlement_type = (
            OnlyStrategyCashEntryType.BUY_SETTLEMENT
            if trade.side is OnlyOrderSide.BUY
            else OnlyStrategyCashEntryType.SELL_SETTLEMENT
        )
        signed_notional = OnlyMoney(
            -notional.amount if trade.side is OnlyOrderSide.BUY else notional.amount,
            self.key.base_currency,
        )
        self._record_cash(
            settlement_type,
            signed_notional,
            trade.ts_event,
            trade.ts_init,
            order_id=trade.order_id,
            trade_id=trade.trade_id,
        )
        if trade.fee.amount:
            self._record_cash(
                OnlyStrategyCashEntryType.FEE,
                OnlyMoney(-trade.fee.amount, self.key.base_currency),
                trade.ts_event,
                trade.ts_init,
                order_id=trade.order_id,
                trade_id=trade.trade_id,
            )
        self.trade_count += 1
        if accounting.realized_pnl_delta.amount:
            self.realized_pnl_delta_count += 1
            if accounting.realized_pnl_delta.amount > 0:
                self.winning_trade_count += 1
                self.gross_profit = self.gross_profit + accounting.realized_pnl_delta
            else:
                self.losing_trade_count += 1
                self.gross_loss = self.gross_loss + accounting.realized_pnl_delta
        self.last_trade_sequence = trade.external_sequence
        self.last_trade_order = trade.stable_order
        self.updated_at = trade.ts_event
        self.valuation_time = trade.ts_event
        self.version += 1
        self._reconcile_equity()
        return cash_delta, accounting.realized_pnl_delta, trade.fee

    def apply_fee(self, entry: OnlyStrategyFeeEntry) -> None:
        self._require_active()
        self._require_currency(entry.amount)
        if self.cash_balance.amount < entry.amount.amount:
            raise OnlyStrategyLedgerInsufficientCashError("Fee would make Strategy cash negative")
        self.cash_balance = self.cash_balance - entry.amount
        self.fees = self.fees + entry.amount
        self.fee_entries.append(entry)
        self._record_cash(
            OnlyStrategyCashEntryType.FEE,
            OnlyMoney(-entry.amount.amount, self.key.base_currency),
            entry.ts_event,
            entry.ts_init,
            order_id=entry.order_id,
            trade_id=entry.trade_id,
        )
        self.updated_at = entry.ts_event
        self.version += 1
        self._reconcile_equity()

    def apply_external_cash_flow(
        self,
        cash_flow_id: OnlyStrategyCashFlowId,
        amount: OnlyMoney,
        timestamp: OnlyTimestamp,
    ) -> None:
        self._require_active()
        self._require_currency(amount)
        if self.cash_balance.amount + amount.amount < 0:
            raise OnlyStrategyLedgerInsufficientCashError("cash adjustment would make cash negative")
        self.cash_balance = self.cash_balance + amount
        self.external_cash_flow = self.external_cash_flow + amount
        self._record_cash(
            OnlyStrategyCashEntryType.MANUAL_ADJUSTMENT,
            amount,
            timestamp,
            timestamp,
            cash_flow_id=cash_flow_id,
        )
        self.updated_at = timestamp
        self.version += 1
        self._reconcile_equity()

    def apply_valuation(
        self,
        valuation: OnlyStrategyValuation,
        trading_day: OnlyTradingDay | None,
    ) -> None:
        self._require_active()
        if valuation.key != self.key:
            raise ValueError("Strategy Valuation belongs to another Ledger")
        if trading_day is not None and trading_day != self.trading_day:
            self.trading_day = trading_day
            self.day_start_equity = self._equity
        self.position_cost = valuation.position_cost
        self.position_market_value = valuation.position_market_value
        self.unrealized_pnl = valuation.unrealized_pnl
        self._valuation_lines = {item.instrument_id: item for item in valuation.lines}
        self.updated_at = valuation.ts_event
        self.valuation_time = valuation.ts_event
        self.version += 1
        self._reconcile_equity()

    def reservation_changed(self, timestamp: OnlyTimestamp) -> None:
        self.updated_at = timestamp
        self.version += 1

    def record_reservation(
        self,
        reservation: OnlyStrategyCashReservation,
        entry_type: OnlyStrategyCashEntryType,
        amount: OnlyMoney,
        timestamp: OnlyTimestamp,
    ) -> None:
        """Record a Reservation audit fact without changing cash balance."""

        self._require_active()
        self._require_currency(amount)
        self._record_cash(
            entry_type,
            amount,
            timestamp,
            timestamp,
            order_id=reservation.order_id,
            reservation_id=reservation.reservation_id,
        )
        self.reservation_changed(timestamp)

    def _update_trade_valuation(self, accounting: OnlyStrategyTradeAccountingInput) -> None:
        allocation = accounting.position_allocation_after
        instrument_id = accounting.trade.instrument_id
        if allocation is None or allocation.total_quantity.value == 0:
            self._valuation_lines.pop(instrument_id, None)
        else:
            if allocation.average_open_price is None:
                raise ValueError("open Allocation requires average price")
            quantum = Decimal(1).scaleb(-self.key.base_currency.precision)
            multiplier = accounting.trade.multiplier.value
            cost = (allocation.average_open_price.value * allocation.total_quantity.value * multiplier).quantize(
                quantum, ROUND_HALF_EVEN
            )
            market = (accounting.trade.price.value * allocation.total_quantity.value * multiplier).quantize(
                quantum, ROUND_HALF_EVEN
            )
            self._valuation_lines[instrument_id] = OnlyStrategyValuationLine(
                instrument_id,
                OnlyMoney(cost, self.key.base_currency),
                OnlyMoney(market, self.key.base_currency),
                OnlyMoney(market - cost, self.key.base_currency),
                accounting.trade.price,
                accounting.sequence,
            )
        zero = only_zero_money(self.key.base_currency)
        self.position_cost = self._sum_line("position_cost", zero)
        self.position_market_value = self._sum_line("position_market_value", zero)
        self.unrealized_pnl = self._sum_line("unrealized_pnl", zero)

    def _sum_line(self, field_name: str, zero: OnlyMoney) -> OnlyMoney:
        result = zero
        for line in self._valuation_lines.values():
            value = getattr(line, field_name)
            if not isinstance(value, OnlyMoney):
                raise TypeError("Strategy valuation line field is not Money")
            result = result + value
        return result

    def _reconcile_equity(self) -> None:
        cash_view = self.cash_balance + self.position_market_value
        pnl_view = self.initial_capital + self.external_cash_flow + self.realized_pnl + self.unrealized_pnl - self.fees
        if cash_view != pnl_view:
            self.status = OnlyStrategyLedgerStatus.RECONCILING
            self.quality_flags = tuple(sorted(set(self.quality_flags + ("EQUITY_VIEW_MISMATCH",))))
            return
        self._equity = cash_view
        if self.status is OnlyStrategyLedgerStatus.RECONCILING:
            self.status = OnlyStrategyLedgerStatus.ACTIVE
        self.quality_flags = tuple(item for item in self.quality_flags if item != "EQUITY_VIEW_MISMATCH")
        if self._equity.amount > self.high_water_mark.amount:
            self.high_water_mark = self._equity
        drawdown = self._drawdown(self._equity)
        if drawdown.value < self.maximum_drawdown.value:
            self.maximum_drawdown = drawdown

    def _drawdown(self, equity: OnlyMoney) -> OnlyRate:
        if self.high_water_mark.amount <= 0:
            return OnlyRate(Decimal(0), 8)
        return self._rate((equity.amount - self.high_water_mark.amount) / self.high_water_mark.amount)

    def _simple_return(self, equity: OnlyMoney) -> OnlyRate | None:
        if self.external_cash_flow.amount != 0 or self.initial_capital.amount <= 0:
            return None
        return self._rate((equity.amount - self.initial_capital.amount) / self.initial_capital.amount)

    def _daily_return(self, daily_pnl: OnlyMoney) -> OnlyRate | None:
        if self.day_start_equity.amount <= 0:
            return None
        return self._rate(daily_pnl.amount / self.day_start_equity.amount)

    def _win_rate(self) -> OnlyRate | None:
        decisions = self.winning_trade_count + self.losing_trade_count
        return None if decisions == 0 else self._rate(Decimal(self.winning_trade_count) / Decimal(decisions))

    def _profit_factor(self) -> OnlyRate | None:
        if self.gross_loss.amount == 0:
            return None
        return self._rate(self.gross_profit.amount / abs(self.gross_loss.amount))

    @staticmethod
    def _rate(value: Decimal) -> OnlyRate:
        return OnlyRate(value.quantize(Decimal("0.00000001"), ROUND_HALF_EVEN), 8)

    def _notional(self, accounting: OnlyStrategyTradeAccountingInput) -> OnlyMoney:
        quantum = Decimal(1).scaleb(-self.key.base_currency.precision)
        amount = (
            accounting.trade.price.value * accounting.trade.quantity.value * accounting.trade.multiplier.value
        ).quantize(quantum, ROUND_HALF_EVEN)
        return OnlyMoney(amount, self.key.base_currency)

    def _allocation_realized_delta(self, accounting: OnlyStrategyTradeAccountingInput) -> OnlyMoney:
        zero = only_zero_money(self.key.base_currency)
        before = accounting.position_allocation_before
        after = accounting.position_allocation_after
        before_value = zero if before is None else before.realized_pnl
        after_value = zero if after is None else after.realized_pnl
        return after_value - before_value

    def _allocation_cost_delta(self, accounting: OnlyStrategyTradeAccountingInput) -> OnlyMoney:
        def cost(snapshot: object) -> OnlyMoney:
            from onlyalpha.position.models import OnlyPositionAllocationSnapshot

            if not isinstance(snapshot, OnlyPositionAllocationSnapshot):
                return only_zero_money(self.key.base_currency)
            if snapshot.average_open_price is None:
                return only_zero_money(self.key.base_currency)
            quantum = Decimal(1).scaleb(-self.key.base_currency.precision)
            amount = (
                snapshot.average_open_price.value * snapshot.total_quantity.value * accounting.trade.multiplier.value
            ).quantize(quantum, ROUND_HALF_EVEN)
            return OnlyMoney(amount, self.key.base_currency)

        return cost(accounting.position_allocation_after) - cost(accounting.position_allocation_before)

    def _record_cash(
        self,
        entry_type: OnlyStrategyCashEntryType,
        amount: OnlyMoney,
        ts_event: OnlyTimestamp,
        ts_init: OnlyTimestamp,
        *,
        order_id: OnlyOrderId | None = None,
        trade_id: OnlyTradeId | None = None,
        reservation_id: object | None = None,
        cash_flow_id: OnlyStrategyCashFlowId | None = None,
    ) -> None:
        self._entry_sequence += 1
        from onlyalpha.strategy_ledger.identifiers import OnlyStrategyCashReservationId

        typed_reservation = reservation_id if isinstance(reservation_id, OnlyStrategyCashReservationId) else None
        self.cash_entries.append(
            OnlyStrategyCashEntry(
                OnlyStrategyCashEntryId(f"SCASH-{self.ledger_id}-{self._entry_sequence:010d}"),
                self.key.runtime_id,
                self.key.account_id,
                self.key.cluster_id,
                self.key.base_currency,
                amount,
                entry_type,
                order_id,
                trade_id,
                typed_reservation,
                cash_flow_id,
                ts_event,
                ts_init,
                self._entry_sequence,
            )
        )

    def _require_currency(self, amount: OnlyMoney) -> None:
        if amount.currency != self.key.base_currency:
            raise OnlyStrategyLedgerCurrencyError("unsupported currency conversion")

    def _require_active(self) -> None:
        if self.status not in {OnlyStrategyLedgerStatus.ACTIVE, OnlyStrategyLedgerStatus.RECONCILING}:
            raise ValueError(f"Strategy Ledger does not accept updates in {self.status.value}")
