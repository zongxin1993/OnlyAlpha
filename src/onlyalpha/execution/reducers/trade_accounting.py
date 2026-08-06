"""Pure Account and Strategy Ledger reducers for Generic T0 BUY OPEN."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.value import OnlyMoney, OnlyPrice
from onlyalpha.event.model import OnlyEventSource, OnlyEventType
from onlyalpha.strategy_ledger.enums import OnlyStrategyCashEntryType, OnlyStrategyFeeType
from onlyalpha.strategy_ledger.identifiers import OnlyStrategyCashEntryId, OnlyStrategyFeeEntryId
from onlyalpha.strategy_ledger.models import OnlyStrategyCashEntry, OnlyStrategyFeeEntry
from onlyalpha.transaction.projection import (
    OnlyAccountExecutionProjection,
    OnlyRuntimeProjectionComponent,
    OnlyStrategyLedgerExecutionProjection,
)
from onlyalpha.transaction.projection_builder import OnlyRuntimeProjectionBuilder

from ..execution_state import (
    OnlyAccountExecutionState,
    OnlyAllocationExecutionState,
    OnlyStrategyLedgerExecutionState,
)
from ..planned_trade import OnlyPlannedTrade
from ..planning_results import OnlyExecutionEventIntent
from .trade_reservations import (
    OnlyAccountCashReservationTradeReduction,
    OnlyStrategyCashReservationTradeReduction,
)


@dataclass(frozen=True, slots=True)
class OnlyAccountTradeReduction:
    after: OnlyAccountExecutionState
    projection: OnlyAccountExecutionProjection
    cash_delta: OnlyMoney
    fee_delta: OnlyMoney
    event_intents: tuple[OnlyExecutionEventIntent, ...]


@dataclass(frozen=True, slots=True)
class OnlyStrategyLedgerTradeReduction:
    after: OnlyStrategyLedgerExecutionState
    projection: OnlyStrategyLedgerExecutionProjection
    cash_delta: OnlyMoney
    fee_delta: OnlyMoney
    event_intents: tuple[OnlyExecutionEventIntent, ...]


class OnlyAccountTradeReducer:
    def reduce(
        self,
        before: OnlyAccountExecutionState,
        reservation_reduction: OnlyAccountCashReservationTradeReduction | None,
        trade: OnlyPlannedTrade,
        position_market_value_delta: OnlyMoney,
        position_unrealized_pnl: OnlyMoney,
        realized_pnl_delta: OnlyMoney | None = None,
        cash_withdrawable: bool = True,
        *,
        projection_sequence: int,
    ) -> OnlyAccountTradeReduction:
        closing = trade.side is OnlyOrderSide.SELL
        if closing and realized_pnl_delta is None:
            raise ValueError("CLOSE_REALIZED_PNL_AUTHORITY_CONFLICT")
        if not closing and reservation_reduction is None:
            raise ValueError("BUY OPEN requires Account cash Reservation reduction")
        realized = realized_pnl_delta or OnlyMoney(Decimal(0), before.base_currency)
        cash_delta = OnlyMoney(
            (
                trade.settled_notional.amount - trade.fee_charges.amount + trade.fee_rebates.amount
                if closing
                else -(trade.settled_notional.amount + trade.fee_charges.amount - trade.fee_rebates.amount)
            ),
            before.base_currency,
        )
        cash = before.ledger_cash + cash_delta
        if cash.amount < 0:
            raise ValueError("Trade would create negative Account cash")
        reservation_consumed = (
            Decimal(0) if reservation_reduction is None else reservation_reduction.consumed_delta.amount
        )
        reservation_released = (
            Decimal(0) if reservation_reduction is None else reservation_reduction.released_delta.amount
        )
        frozen = OnlyMoney(
            before.order_reserved_cash.amount - reservation_consumed - reservation_released, before.base_currency
        )
        if frozen.amount < 0:
            raise ValueError("Account frozen cash is smaller than Reservation")
        market_value = before.position_market_value + position_market_value_delta
        unsettled = OnlyMoney(
            before.unsettled_receivable_cash.amount
            + (cash_delta.amount if closing and not cash_withdrawable else Decimal(0)),
            before.base_currency,
        )
        available = OnlyMoney(cash.amount - frozen.amount, before.base_currency)
        withdrawable = OnlyMoney(available.amount - unsettled.amount, before.base_currency)
        reserved_margin = before.reserved_margin
        occupied_margin = before.occupied_margin
        available_margin = None
        if reserved_margin is not None and occupied_margin is not None:
            available_margin = OnlyMoney(
                cash.amount - frozen.amount - unsettled.amount - reserved_margin.amount - occupied_margin.amount,
                before.base_currency,
            )
        after = replace(
            before,
            ledger_cash=cash,
            trade_available_cash=available,
            withdrawable_cash=withdrawable,
            order_reserved_cash=frozen,
            unsettled_receivable_cash=unsettled,
            position_market_value=market_value,
            realized_pnl=before.realized_pnl + realized,
            unrealized_pnl=position_unrealized_pnl,
            fees=before.fees + trade.fee_charges - trade.fee_rebates,
            equity=cash + market_value,
            updated_at=trade.ts_init,
            valuation_time=trade.ts_init,
            version=before.version + 4,
            last_external_sequence=trade.source_sequence,
            available_margin=available_margin,
        )
        builder = OnlyRuntimeProjectionBuilder()
        projection = OnlyAccountExecutionProjection(
            builder.identity(
                component=OnlyRuntimeProjectionComponent.ACCOUNT,
                entity_key=str(after.account_id),
                before=before,
                after=after,
                projection_sequence=projection_sequence,
            ),
            before,
            after,
        )
        projection = builder.finalize(projection)
        assert isinstance(projection, OnlyAccountExecutionProjection)
        return OnlyAccountTradeReduction(
            after,
            projection,
            cash_delta,
            trade.fee_charges - trade.fee_rebates,
            (
                _intent(OnlyRuntimeProjectionComponent.ACCOUNT, "ACCOUNT_TRADE_APPLIED", after),
                _intent(OnlyRuntimeProjectionComponent.ACCOUNT, "ACCOUNT_VALUED", after),
            ),
        )


class OnlyStrategyLedgerTradeReducer:
    def reduce(
        self,
        before: OnlyStrategyLedgerExecutionState,
        reservation_reduction: OnlyStrategyCashReservationTradeReduction | None,
        allocation_before: OnlyAllocationExecutionState | None,
        allocation_after: OnlyAllocationExecutionState,
        trade: OnlyPlannedTrade,
        valuation_price: OnlyPrice,
        realized_pnl_delta: OnlyMoney | None = None,
        *,
        projection_sequence: int,
    ) -> OnlyStrategyLedgerTradeReduction:
        currency = before.key.base_currency
        closing = trade.side is OnlyOrderSide.SELL
        if closing and realized_pnl_delta is None:
            raise ValueError("CLOSE_REALIZED_PNL_AUTHORITY_CONFLICT")
        if not closing and reservation_reduction is None:
            raise ValueError("BUY OPEN requires Strategy cash Reservation reduction")
        realized = realized_pnl_delta or OnlyMoney(Decimal(0), currency)
        cash_delta = OnlyMoney(
            (
                trade.settled_notional.amount - trade.fee_charges.amount + trade.fee_rebates.amount
                if closing
                else -(trade.settled_notional.amount + trade.fee_charges.amount - trade.fee_rebates.amount)
            ),
            currency,
        )
        cash = before.ledger_cash + cash_delta
        if cash.amount < 0:
            raise ValueError("Trade would create negative Strategy Ledger cash")
        quantum = Decimal(1).scaleb(-currency.precision)
        position_cost = OnlyMoney(
            (allocation_after.cumulative_open_price_quantity * trade.multiplier.value).quantize(quantum),
            currency,
        )
        del allocation_before
        after_market = allocation_after.total_quantity.value * valuation_price.value * trade.multiplier.value
        market_value = OnlyMoney(after_market.quantize(quantum), currency)
        reservation_consumed = (
            Decimal(0) if reservation_reduction is None else reservation_reduction.consumed_delta.amount
        )
        reservation_released = (
            Decimal(0) if reservation_reduction is None else reservation_reduction.released_delta.amount
        )
        cash_reserved = OnlyMoney(before.cash_reserved.amount - reservation_consumed - reservation_released, currency)
        if cash_reserved.amount < 0:
            raise ValueError("Strategy Ledger reserved cash is smaller than Reservation")
        entry_sequence = max((entry.sequence for entry in before.cash_entries), default=0)
        settlement_entry = OnlyStrategyCashEntry(
            OnlyStrategyCashEntryId(f"SCASH-{before.ledger_id}-{entry_sequence + 1:010d}"),
            before.key.runtime_id,
            before.key.account_id,
            before.key.cluster_id,
            currency,
            OnlyMoney(
                trade.settled_notional.amount if closing else -trade.settled_notional.amount,
                currency,
            ),
            OnlyStrategyCashEntryType.SELL_SETTLEMENT if closing else OnlyStrategyCashEntryType.BUY_SETTLEMENT,
            trade.order_id,
            trade.trade_id,
            None,
            None,
            trade.ts_event,
            trade.ts_init,
            entry_sequence + 1,
        )
        cash_entries = before.cash_entries + (settlement_entry,)
        if trade.fee_charges.amount or trade.fee_rebates.amount:
            cash_entries += (
                OnlyStrategyCashEntry(
                    OnlyStrategyCashEntryId(f"SCASH-{before.ledger_id}-{entry_sequence + 2:010d}"),
                    before.key.runtime_id,
                    before.key.account_id,
                    before.key.cluster_id,
                    currency,
                    OnlyMoney(trade.fee_rebates.amount - trade.fee_charges.amount, currency),
                    OnlyStrategyCashEntryType.FEE,
                    trade.order_id,
                    trade.trade_id,
                    None,
                    None,
                    trade.ts_event,
                    trade.ts_init,
                    entry_sequence + 2,
                ),
            )
        if reservation_reduction is not None and reservation_reduction.released_delta.amount:
            release_sequence = max((entry.sequence for entry in cash_entries), default=0) + 1
            cash_entries += (
                OnlyStrategyCashEntry(
                    OnlyStrategyCashEntryId(f"SCASH-{before.ledger_id}-{release_sequence:010d}"),
                    before.key.runtime_id,
                    before.key.account_id,
                    before.key.cluster_id,
                    currency,
                    reservation_reduction.released_delta,
                    OnlyStrategyCashEntryType.ORDER_RESERVATION_RELEASE,
                    trade.order_id,
                    None,
                    reservation_reduction.after.reservation_id,
                    None,
                    trade.ts_init,
                    trade.ts_init,
                    release_sequence,
                ),
            )
        if allocation_after.average_open_price is None and allocation_after.total_quantity.value:
            raise ValueError("open Allocation requires average price")
        fee_entries = before.fee_entries
        if trade.fee_charges.amount or trade.fee_rebates.amount:
            fee_entries += (
                OnlyStrategyFeeEntry(
                    OnlyStrategyFeeEntryId(f"SFEE-{trade.runtime_id}-{trade.trade_id}"),
                    before.key,
                    trade.fee_charges - trade.fee_rebates,
                    OnlyStrategyFeeType.COMMISSION,
                    trade.trade_id,
                    trade.order_id,
                    trade.ts_event,
                    trade.ts_init,
                    trade.source_sequence,
                ),
            )
        unrealized = OnlyMoney(
            Decimal(0)
            if allocation_after.average_open_price is None
            else (
                (valuation_price.value - allocation_after.average_open_price.value)
                * allocation_after.total_quantity.value
                * trade.multiplier.value
            ).quantize(quantum),
            currency,
        )
        after = replace(
            before,
            ledger_cash=cash,
            cash_reserved=cash_reserved,
            cash_available=OnlyMoney(cash.amount - cash_reserved.amount, currency),
            position_cost=position_cost,
            position_market_value=market_value,
            realized_pnl=before.realized_pnl + realized,
            unrealized_pnl=unrealized,
            fees=before.fees + trade.fee_charges - trade.fee_rebates,
            equity=cash + market_value,
            cash_entries=cash_entries,
            fee_entries=fee_entries,
            updated_at=trade.ts_init,
            valuation_time=trade.ts_event,
            trading_day=trade.trading_day,
            version=before.version + 4,
            last_trade_sequence=trade.source_sequence,
            last_trade_order=trade.stable_order,
        )
        builder = OnlyRuntimeProjectionBuilder()
        projection = OnlyStrategyLedgerExecutionProjection(
            builder.identity(
                component=OnlyRuntimeProjectionComponent.STRATEGY_LEDGER,
                entity_key=str(after.ledger_id),
                before=before,
                after=after,
                projection_sequence=projection_sequence,
            ),
            before,
            after,
        )
        projection = builder.finalize(projection)
        assert isinstance(projection, OnlyStrategyLedgerExecutionProjection)
        return OnlyStrategyLedgerTradeReduction(
            after,
            projection,
            cash_delta,
            trade.fee_charges - trade.fee_rebates,
            (
                _intent(OnlyRuntimeProjectionComponent.STRATEGY_LEDGER, "STRATEGY_TRADE_APPLIED", after),
                _intent(OnlyRuntimeProjectionComponent.STRATEGY_LEDGER, "STRATEGY_VALUATION_UPDATED", after),
            ),
        )


def _intent(component: OnlyRuntimeProjectionComponent, event_type: str, payload: object) -> OnlyExecutionEventIntent:
    encoded = payload.to_dict() if hasattr(payload, "to_dict") else payload
    return OnlyExecutionEventIntent(
        component, OnlyEventType(event_type), encoded, OnlyEventSource("execution.trade_planner")
    )


__all__ = [name for name in globals() if name.startswith("Only")]
