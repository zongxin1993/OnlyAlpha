"""Pure Order, Position, Allocation, Settlement, Fee and Valuation reducers."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import ROUND_HALF_EVEN, Decimal

from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha.event.model import OnlyEventSource, OnlyEventType
from onlyalpha.fee.models import OnlyFeeInstruction
from onlyalpha.market.runtime_rules import OnlySettlementRuntimeInstruction
from onlyalpha.position.enums import OnlyPositionStatus, OnlySettlementBucket
from onlyalpha.position.keys import OnlyPositionAllocationKey, OnlyPositionKey

from ..execution_state import OnlyAllocationExecutionState, OnlyOrderExecutionState, OnlyPositionExecutionState
from ..planned_trade import OnlyPlannedTrade
from ..planning_context import OnlyAllocationCreationAuthority, OnlyPositionCreationAuthority
from ..planning_results import OnlyExecutionEventIntent
from ..projection import (
    OnlyAllocationExecutionProjection,
    OnlyExecutionProjectionComponent,
    OnlyFeeExecutionProjection,
    OnlyFeeExecutionState,
    OnlyFeeInstructionReplay,
    OnlyFeeRecordReplay,
    OnlyOrderExecutionProjection,
    OnlyPositionExecutionProjection,
    OnlySettlementExecutionProjection,
    OnlySettlementExecutionState,
    OnlySettlementRecordReplay,
    OnlyValuationExecutionProjection,
    OnlyValuationExecutionState,
)
from ..projection_builder import OnlyExecutionProjectionBuilder


@dataclass(frozen=True, slots=True)
class OnlyOrderTradeReduction:
    after: OnlyOrderExecutionState
    projection: OnlyOrderExecutionProjection
    event_intents: tuple[OnlyExecutionEventIntent, ...]


@dataclass(frozen=True, slots=True)
class OnlyPositionTradeReduction:
    after: OnlyPositionExecutionState
    projection: OnlyPositionExecutionProjection
    realized_pnl_delta: OnlyMoney
    event_intents: tuple[OnlyExecutionEventIntent, ...]


@dataclass(frozen=True, slots=True)
class OnlyAllocationTradeReduction:
    after: OnlyAllocationExecutionState
    projection: OnlyAllocationExecutionProjection
    realized_pnl_delta: OnlyMoney


@dataclass(frozen=True, slots=True)
class OnlySettlementTradeReduction:
    after: OnlySettlementExecutionState
    projection: OnlySettlementExecutionProjection
    event_intents: tuple[OnlyExecutionEventIntent, ...]


@dataclass(frozen=True, slots=True)
class OnlyFeeTradeReduction:
    after: OnlyFeeExecutionState
    projection: OnlyFeeExecutionProjection
    event_intents: tuple[OnlyExecutionEventIntent, ...]


@dataclass(frozen=True, slots=True)
class OnlyValuationTradeReduction:
    after: OnlyValuationExecutionState
    projection: OnlyValuationExecutionProjection


class OnlyOrderTradeReducer:
    def reduce(
        self, before: OnlyOrderExecutionState, trade: OnlyPlannedTrade, *, projection_sequence: int
    ) -> OnlyOrderTradeReduction:
        previous_notional = Decimal(0)
        precision = trade.price.precision
        if before.average_fill_price is not None:
            previous_notional = before.average_fill_price.value * before.filled_quantity.value
            precision = max(precision, before.average_fill_price.precision)
        total = before.filled_quantity.value + trade.quantity.value
        average = OnlyPrice(
            ((previous_notional + trade.price.value * trade.quantity.value) / total).quantize(
                Decimal(1).scaleb(-precision), rounding=ROUND_HALF_EVEN
            ),
            precision,
        )
        after = replace(
            before,
            status=OnlyOrderStatus.FILLED,
            filled_quantity=before.quantity,
            remaining_quantity=OnlyQuantity(Decimal(0), before.quantity.precision),
            average_fill_price=average,
            updated_at=trade.ts_init,
            filled_at=trade.ts_event,
            version=before.version + 1,
            last_external_sequence=trade.source_sequence,
        )
        builder = OnlyExecutionProjectionBuilder()
        projection = OnlyOrderExecutionProjection(
            builder.identity(
                component=OnlyExecutionProjectionComponent.ORDER,
                entity_key=str(before.order_id),
                before=before,
                after=after,
                projection_sequence=projection_sequence,
            ),
            before,
            after,
            trade.fill,
            trade.broker_update_id,
        )
        projection = builder.finalize(projection)
        assert isinstance(projection, OnlyOrderExecutionProjection)
        return OnlyOrderTradeReduction(
            after,
            projection,
            (_intent(OnlyExecutionProjectionComponent.ORDER, "ORDER_FILLED", after.to_dict()),),
        )


class OnlyPositionTradeReducer:
    def reduce(
        self,
        before: OnlyPositionExecutionState | None,
        trade: OnlyPlannedTrade,
        creation: OnlyPositionCreationAuthority | None,
        *,
        projection_sequence: int,
    ) -> OnlyPositionTradeReduction:
        zero_quantity = OnlyQuantity(Decimal(0), trade.quantity.precision)
        zero_money = OnlyMoney(Decimal(0), trade.authoritative_fee.currency)
        if before is None:
            assert creation is not None
            total_before = zero_quantity
            settled_before = zero_quantity
            unsettled_before = zero_quantity
            average_before = None
            realized_before = zero_money
            fees_before = zero_money
            opened_at = trade.ts_event
            order_frozen = zero_quantity
            risk_reserved = zero_quantity
            restricted = zero_quantity
            quality_flags: tuple[str, ...] = ()
            broker_available = None
            version = 1
        else:
            total_before = before.total_quantity
            settled_before = before.settled_quantity
            unsettled_before = before.unsettled_quantity
            average_before = before.average_open_price
            realized_before = before.realized_pnl
            fees_before = before.fees
            opened_at = before.opened_at
            order_frozen = before.order_frozen_quantity
            risk_reserved = before.risk_reserved_quantity
            restricted = before.restricted_quantity
            quality_flags = before.quality_flags
            broker_available = before.broker_available_quantity
            version = before.version + 1
        total_value = total_before.value + trade.quantity.value
        average = _average_open_price(average_before, total_before, trade.price, trade.quantity)
        settled = (
            settled_before + trade.quantity
            if trade.settlement_bucket is OnlySettlementBucket.SETTLED
            else settled_before
        )
        unsettled = (
            unsettled_before + trade.quantity
            if trade.settlement_bucket is OnlySettlementBucket.UNSETTLED
            else unsettled_before
        )
        after = OnlyPositionExecutionState(
            creation.position_id if before is None and creation is not None else before.position_id,  # type: ignore[union-attr]
            trade_position_key(trade),
            OnlyPositionStatus.OPEN,
            OnlyQuantity(total_value, max(total_before.precision, trade.quantity.precision)),
            settled,
            unsettled,
            order_frozen,
            risk_reserved,
            restricted,
            average,
            realized_before,
            fees_before + trade.authoritative_fee,
            opened_at,
            trade.ts_event,
            None,
            version,
            trade.source_sequence,
            trade.stable_order,
            quality_flags,
            broker_available,
        )
        zero = OnlyMoney(Decimal(0), trade.authoritative_fee.currency)
        builder = OnlyExecutionProjectionBuilder()
        projection = OnlyPositionExecutionProjection(
            builder.identity(
                component=OnlyExecutionProjectionComponent.POSITION,
                entity_key=str(after.position_id),
                before=before,
                after=after,
                projection_sequence=projection_sequence,
            ),
            before,
            after,
            zero,
        )
        projection = builder.finalize(projection)
        assert isinstance(projection, OnlyPositionExecutionProjection)
        event_type = "POSITION_OPENED" if before is None else "POSITION_INCREASED"
        return OnlyPositionTradeReduction(
            after,
            projection,
            zero,
            (_intent(OnlyExecutionProjectionComponent.POSITION, event_type, after.to_dict()),),
        )


class OnlyAllocationTradeReducer:
    def reduce(
        self,
        before: OnlyAllocationExecutionState | None,
        trade: OnlyPlannedTrade,
        creation: OnlyAllocationCreationAuthority | None,
        *,
        projection_sequence: int,
    ) -> OnlyAllocationTradeReduction:
        zero_quantity = OnlyQuantity(Decimal(0), trade.quantity.precision)
        zero_money = OnlyMoney(Decimal(0), trade.authoritative_fee.currency)
        if before is None:
            assert creation is not None
            total_before = settled_before = unsettled_before = zero_quantity
            average_before = None
            realized_before = fees_before = zero_money
            opened_at = trade.ts_event
            order_frozen = risk_reserved = restricted = zero_quantity
            version = 1
        else:
            total_before = before.total_quantity
            settled_before = before.settled_quantity
            unsettled_before = before.unsettled_quantity
            average_before = before.average_open_price
            realized_before = before.realized_pnl
            fees_before = before.fees
            opened_at = before.opened_at
            order_frozen = before.order_frozen_quantity
            risk_reserved = before.risk_reserved_quantity
            restricted = before.restricted_quantity
            version = before.version + 1
        settled = (
            settled_before + trade.quantity
            if trade.settlement_bucket is OnlySettlementBucket.SETTLED
            else settled_before
        )
        unsettled = (
            unsettled_before + trade.quantity
            if trade.settlement_bucket is OnlySettlementBucket.UNSETTLED
            else unsettled_before
        )
        after = OnlyAllocationExecutionState(
            creation.allocation_id if before is None and creation is not None else before.allocation_id,  # type: ignore[union-attr]
            trade_allocation_key(trade),
            OnlyQuantity(
                total_before.value + trade.quantity.value, max(total_before.precision, trade.quantity.precision)
            ),
            settled,
            unsettled,
            order_frozen,
            risk_reserved,
            restricted,
            _average_open_price(average_before, total_before, trade.price, trade.quantity),
            realized_before,
            fees_before + trade.authoritative_fee,
            opened_at,
            trade.ts_event,
            None,
            version,
            trade.source_sequence,
            trade.stable_order,
        )
        builder = OnlyExecutionProjectionBuilder()
        projection = OnlyAllocationExecutionProjection(
            builder.identity(
                component=OnlyExecutionProjectionComponent.ALLOCATION,
                entity_key=str(after.allocation_id),
                before=before,
                after=after,
                projection_sequence=projection_sequence,
            ),
            before,
            after,
            zero_money,
        )
        projection = builder.finalize(projection)
        assert isinstance(projection, OnlyAllocationExecutionProjection)
        return OnlyAllocationTradeReduction(after, projection, zero_money)


class OnlySettlementTradeReducer:
    def reduce(
        self,
        before: OnlySettlementExecutionState | None,
        instruction: OnlySettlementRuntimeInstruction,
        trading_day: OnlyTradingDay,
        trade: OnlyPlannedTrade,
        *,
        record_sequence: int,
        projection_sequence: int,
    ) -> OnlySettlementTradeReduction:
        currency = trade.authoritative_fee.currency
        flags_before = (
            (False, False, False, False)
            if before is None
            else (
                before.asset_released,
                before.trade_cash_released,
                before.withdrawable_cash_released,
                before.legal_settled,
            )
        )
        flags_after = (
            flags_before[0] or trading_day >= instruction.asset_available_on,
            flags_before[1] or trading_day >= instruction.cash_trade_available_on,
            flags_before[2] or trading_day >= instruction.cash_withdrawable_on,
            flags_before[3] or trading_day >= instruction.legal_settlement_on,
        )
        after = OnlySettlementExecutionState(
            instruction.instruction_id,
            trade.account_id,
            trade.instrument_id,
            trade.order_id,
            instruction.source_trade_id,
            instruction.asset_quantity,
            _money(instruction.cash_amount, currency),
            *flags_after,
            instruction.asset_available_on,
            instruction.cash_trade_available_on,
            instruction.cash_withdrawable_on,
            instruction.legal_settlement_on,
            1 if before is None else before.version + 1,
        )
        records: tuple[OnlySettlementRecordReplay, ...] = ()
        if flags_before != flags_after:
            records = (
                OnlySettlementRecordReplay(
                    instruction.instruction_id,
                    after.account_id,
                    after.instrument_id,
                    after.source_order_id,
                    after.source_trade_id,
                    trading_day,
                    instruction.asset_quantity if flags_after[0] else Decimal(0),
                    _money(instruction.cash_amount if flags_after[1] else Decimal(0), currency),
                    _money(instruction.cash_amount if flags_after[2] else Decimal(0), currency),
                    flags_after[3],
                    record_sequence + 1,
                ),
            )
        builder = OnlyExecutionProjectionBuilder()
        projection = OnlySettlementExecutionProjection(
            builder.identity(
                component=OnlyExecutionProjectionComponent.SETTLEMENT,
                entity_key=after.instruction_id,
                before=before,
                after=after,
                projection_sequence=projection_sequence,
            ),
            before,
            after,
            records,
        )
        projection = builder.finalize(projection)
        assert isinstance(projection, OnlySettlementExecutionProjection)
        intents = (
            ()
            if not records
            else (_intent(OnlyExecutionProjectionComponent.SETTLEMENT, "SETTLEMENT_UPDATED", after.to_dict()),)
        )
        return OnlySettlementTradeReduction(after, projection, intents)


class OnlyFeeTradeReducer:
    def reduce(
        self,
        before: OnlyFeeExecutionState | None,
        instruction: OnlyFeeInstruction,
        instrument_id: object,
        *,
        record_sequence: int,
        projection_sequence: int,
    ) -> OnlyFeeTradeReduction:
        del instrument_id
        records = tuple(
            OnlyFeeRecordReplay(
                f"FEE-{instruction.instruction_id}-{record_sequence + index:08d}",
                instruction.instruction_id,
                instruction.account_id,
                instruction.order_id,
                instruction.trade_id,
                component.amount,
                component.fee_type.value,
            )
            for index, component in enumerate(instruction.fee_breakdown.components, start=1)
        )
        replay = OnlyFeeInstructionReplay(
            instruction.instruction_id,
            instruction.runtime_id,
            instruction.cluster_id,
            instruction.account_id,
            instruction.order_id,
            instruction.trade_id,
            instruction.calculation_source,
            instruction.idempotency_key,
            OnlyTimestamp.from_datetime(instruction.created_at),
        )
        after = OnlyFeeExecutionState(
            replay,
            records,
            instruction.fee_breakdown.total,
            instruction.fee_breakdown,
            1 if before is None else before.version + 1,
        )
        builder = OnlyExecutionProjectionBuilder()
        projection = OnlyFeeExecutionProjection(
            builder.identity(
                component=OnlyExecutionProjectionComponent.FEE,
                entity_key=instruction.instruction_id,
                before=before,
                after=after,
                projection_sequence=projection_sequence,
            ),
            before,
            after,
        )
        projection = builder.finalize(projection)
        assert isinstance(projection, OnlyFeeExecutionProjection)
        intents = (
            () if not records else (_intent(OnlyExecutionProjectionComponent.FEE, "FEE_RECORDED", after.to_dict()),)
        )
        return OnlyFeeTradeReduction(after, projection, intents)


class OnlyValuationTradeReducer:
    def reduce(
        self,
        before: OnlyValuationExecutionState,
        trade: OnlyPlannedTrade,
        account_cash: OnlyMoney,
        position_market_value: OnlyMoney,
        unrealized_pnl: OnlyMoney,
        *,
        projection_sequence: int,
    ) -> OnlyValuationTradeReduction:
        after = replace(
            before,
            valuation_time=trade.ts_event,
            cash=account_cash,
            position_market_value=position_market_value,
            unrealized_pnl=unrealized_pnl,
            equity=account_cash + position_market_value,
            version=before.version + 1,
        )
        builder = OnlyExecutionProjectionBuilder()
        projection = OnlyValuationExecutionProjection(
            builder.identity(
                component=OnlyExecutionProjectionComponent.VALUATION,
                entity_key=str(after.account_id),
                before=before,
                after=after,
                projection_sequence=projection_sequence,
            ),
            before,
            after,
        )
        projection = builder.finalize(projection)
        assert isinstance(projection, OnlyValuationExecutionProjection)
        return OnlyValuationTradeReduction(after, projection)


def trade_position_key(trade: OnlyPlannedTrade) -> OnlyPositionKey:
    return OnlyPositionKey(
        trade.runtime_id, trade.account_id, trade.instrument_id, trade.position_side, trade.position_mode
    )


def trade_allocation_key(trade: OnlyPlannedTrade) -> OnlyPositionAllocationKey:
    return OnlyPositionAllocationKey(
        trade.runtime_id, trade.account_id, trade.cluster_id, trade.instrument_id, trade.position_side
    )


def _average_open_price(
    before_price: OnlyPrice | None,
    before_quantity: OnlyQuantity,
    fill_price: OnlyPrice,
    fill_quantity: OnlyQuantity,
) -> OnlyPrice:
    new_quantity = before_quantity.value + fill_quantity.value
    raw = (
        fill_price.value
        if before_price is None
        else (before_price.value * before_quantity.value + fill_price.value * fill_quantity.value) / new_quantity
    )
    precision = max(fill_price.precision, 0 if before_price is None else before_price.precision)
    return OnlyPrice(raw.quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_EVEN), precision)


def _money(amount: Decimal, currency: OnlyCurrency) -> OnlyMoney:
    quantum = Decimal(1).scaleb(-currency.precision)
    return OnlyMoney(amount.quantize(quantum), currency)


def _intent(component: OnlyExecutionProjectionComponent, event_type: str, payload: object) -> OnlyExecutionEventIntent:
    return OnlyExecutionEventIntent(
        component, OnlyEventType(event_type), payload, OnlyEventSource("execution.trade_planner")
    )


__all__ = [name for name in globals() if name.startswith("Only")]
