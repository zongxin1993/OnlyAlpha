"""Pure Account and Strategy Ledger reducers for Generic T0 BUY OPEN."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from onlyalpha.domain.value import OnlyMoney, OnlyPrice
from onlyalpha.event.model import OnlyEventSource, OnlyEventType
from onlyalpha.strategy_ledger.enums import OnlyStrategyCashEntryType, OnlyStrategyFeeType
from onlyalpha.strategy_ledger.identifiers import OnlyStrategyCashEntryId, OnlyStrategyFeeEntryId
from onlyalpha.strategy_ledger.models import OnlyStrategyCashEntry, OnlyStrategyFeeEntry

from ..execution_state import (
    OnlyAccountExecutionState,
    OnlyAllocationExecutionState,
    OnlyStrategyLedgerExecutionState,
)
from ..planned_trade import OnlyPlannedTrade
from ..planning_results import OnlyExecutionEventIntent
from ..projection import (
    OnlyAccountExecutionProjection,
    OnlyExecutionProjectionComponent,
    OnlyStrategyLedgerExecutionProjection,
)
from ..projection_builder import OnlyExecutionProjectionBuilder
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
        reservation_reduction: OnlyAccountCashReservationTradeReduction,
        trade: OnlyPlannedTrade,
        position_market_value_delta: OnlyMoney,
        position_unrealized_pnl: OnlyMoney,
        *,
        projection_sequence: int,
    ) -> OnlyAccountTradeReduction:
        cash_delta = OnlyMoney(-(trade.settled_notional.amount + trade.authoritative_fee.amount), before.base_currency)
        cash = before.cash_balance + cash_delta
        if cash.amount < 0:
            raise ValueError("Trade would create negative Account cash")
        frozen = OnlyMoney(
            before.frozen_cash.amount
            - reservation_reduction.consumed_delta.amount
            - reservation_reduction.released_delta.amount,
            before.base_currency,
        )
        if frozen.amount < 0:
            raise ValueError("Account frozen cash is smaller than Reservation")
        market_value = before.position_market_value + position_market_value_delta
        available = OnlyMoney(cash.amount - frozen.amount - before.unsettled_cash.amount, before.base_currency)
        reserved_margin = before.reserved_margin
        occupied_margin = before.occupied_margin
        available_margin = None
        if reserved_margin is not None and occupied_margin is not None:
            available_margin = OnlyMoney(
                cash.amount
                - frozen.amount
                - before.unsettled_cash.amount
                - reserved_margin.amount
                - occupied_margin.amount,
                before.base_currency,
            )
        after = replace(
            before,
            cash_balance=cash,
            available_cash=available,
            frozen_cash=frozen,
            position_market_value=market_value,
            realized_pnl=before.realized_pnl,
            unrealized_pnl=position_unrealized_pnl,
            fees=before.fees + trade.authoritative_fee,
            equity=cash + market_value,
            updated_at=trade.ts_init,
            valuation_time=trade.ts_init,
            version=before.version + 4,
            last_external_sequence=trade.source_sequence,
            available_margin=available_margin,
        )
        builder = OnlyExecutionProjectionBuilder()
        projection = OnlyAccountExecutionProjection(
            builder.identity(
                component=OnlyExecutionProjectionComponent.ACCOUNT,
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
            trade.authoritative_fee,
            (
                _intent(OnlyExecutionProjectionComponent.ACCOUNT, "ACCOUNT_TRADE_APPLIED", after),
                _intent(OnlyExecutionProjectionComponent.ACCOUNT, "ACCOUNT_VALUED", after),
            ),
        )


class OnlyStrategyLedgerTradeReducer:
    def reduce(
        self,
        before: OnlyStrategyLedgerExecutionState,
        reservation_reduction: OnlyStrategyCashReservationTradeReduction,
        allocation_before: OnlyAllocationExecutionState | None,
        allocation_after: OnlyAllocationExecutionState,
        trade: OnlyPlannedTrade,
        valuation_price: OnlyPrice,
        *,
        projection_sequence: int,
    ) -> OnlyStrategyLedgerTradeReduction:
        currency = before.key.base_currency
        cash_delta = OnlyMoney(-(trade.settled_notional.amount + trade.authoritative_fee.amount), currency)
        cash = before.cash_balance + cash_delta
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
        cash_reserved = OnlyMoney(
            before.cash_reserved.amount
            - reservation_reduction.consumed_delta.amount
            - reservation_reduction.released_delta.amount,
            currency,
        )
        if cash_reserved.amount < 0:
            raise ValueError("Strategy Ledger reserved cash is smaller than Reservation")
        entry_sequence = max((entry.sequence for entry in before.cash_entries), default=0)
        settlement_entry = OnlyStrategyCashEntry(
            OnlyStrategyCashEntryId(f"SCASH-{before.ledger_id}-{entry_sequence + 1:010d}"),
            before.key.runtime_id,
            before.key.account_id,
            before.key.cluster_id,
            currency,
            OnlyMoney(-trade.settled_notional.amount, currency),
            OnlyStrategyCashEntryType.BUY_SETTLEMENT,
            trade.order_id,
            trade.trade_id,
            None,
            None,
            trade.ts_event,
            trade.ts_init,
            entry_sequence + 1,
        )
        cash_entries = before.cash_entries + (settlement_entry,)
        if trade.authoritative_fee.amount:
            cash_entries += (
                OnlyStrategyCashEntry(
                    OnlyStrategyCashEntryId(f"SCASH-{before.ledger_id}-{entry_sequence + 2:010d}"),
                    before.key.runtime_id,
                    before.key.account_id,
                    before.key.cluster_id,
                    currency,
                    OnlyMoney(-trade.authoritative_fee.amount, currency),
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
        if reservation_reduction.released_delta.amount:
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
        if allocation_after.average_open_price is None:
            raise ValueError("open Allocation requires average price")
        fee_entries = before.fee_entries
        if trade.authoritative_fee.amount:
            fee_entries += (
                OnlyStrategyFeeEntry(
                    OnlyStrategyFeeEntryId(f"SFEE-{trade.runtime_id}-{trade.trade_id}"),
                    before.key,
                    trade.authoritative_fee,
                    OnlyStrategyFeeType.COMMISSION,
                    trade.trade_id,
                    trade.order_id,
                    trade.ts_event,
                    trade.ts_init,
                    trade.source_sequence,
                ),
            )
        unrealized = OnlyMoney(
            (
                (valuation_price.value - allocation_after.average_open_price.value)
                * allocation_after.total_quantity.value
                * trade.multiplier.value
            ).quantize(quantum),
            currency,
        )
        after = replace(
            before,
            cash_balance=cash,
            cash_reserved=cash_reserved,
            cash_available=OnlyMoney(cash.amount - cash_reserved.amount, currency),
            position_cost=position_cost,
            position_market_value=market_value,
            realized_pnl=before.realized_pnl,
            unrealized_pnl=unrealized,
            fees=before.fees + trade.authoritative_fee,
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
        builder = OnlyExecutionProjectionBuilder()
        projection = OnlyStrategyLedgerExecutionProjection(
            builder.identity(
                component=OnlyExecutionProjectionComponent.STRATEGY_LEDGER,
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
            trade.authoritative_fee,
            (
                _intent(OnlyExecutionProjectionComponent.STRATEGY_LEDGER, "STRATEGY_TRADE_APPLIED", after),
                _intent(OnlyExecutionProjectionComponent.STRATEGY_LEDGER, "STRATEGY_VALUATION_UPDATED", after),
            ),
        )


def _intent(component: OnlyExecutionProjectionComponent, event_type: str, payload: object) -> OnlyExecutionEventIntent:
    encoded = payload.to_dict() if hasattr(payload, "to_dict") else payload
    return OnlyExecutionEventIntent(
        component, OnlyEventType(event_type), encoded, OnlyEventSource("execution.trade_planner")
    )


__all__ = [name for name in globals() if name.startswith("Only")]
