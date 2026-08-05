"""Pure Order, Position, Allocation, Settlement, Fee and Valuation reducers."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import ROUND_HALF_EVEN, Decimal

from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha.event.model import OnlyEventSource, OnlyEventType
from onlyalpha.fee.models import OnlyFeeInstruction
from onlyalpha.market.models import OnlyPositionEffect
from onlyalpha.position.enums import (
    OnlyPositionReservationStage,
    OnlyPositionStatus,
    OnlySettlementBucket,
)
from onlyalpha.position.keys import OnlyPositionAllocationKey, OnlyPositionKey
from onlyalpha.settlement.models import OnlySettlementInstruction
from onlyalpha.transaction.projection import (
    OnlyAllocationExecutionProjection,
    OnlyAllocationExecutionReplayMetadata,
    OnlyFeeExecutionProjection,
    OnlyFeeExecutionState,
    OnlyFeeInstructionReplay,
    OnlyFeeRecordReplay,
    OnlyOrderExecutionProjection,
    OnlyPositionExecutionProjection,
    OnlyPositionExecutionReplayMetadata,
    OnlyRuntimeProjectionComponent,
    OnlySettlementExecutionProjection,
    OnlySettlementExecutionState,
    OnlySettlementRecordReplay,
    OnlyValuationExecutionProjection,
    OnlyValuationExecutionState,
)
from onlyalpha.transaction.projection_builder import OnlyRuntimeProjectionBuilder

from ..close_cost_authority import OnlyAttributedCloseCostAuthority
from ..execution_state import (
    OnlyAllocationExecutionState,
    OnlyOrderExecutionState,
    OnlyPositionExecutionState,
    OnlyPositionReservationExecutionState,
)
from ..planned_trade import OnlyPlannedTrade
from ..planning_context import OnlyAllocationCreationAuthority, OnlyPositionCreationAuthority
from ..planning_results import OnlyExecutionEventIntent


@dataclass(frozen=True, slots=True)
class OnlyOrderTradeReduction:
    after: OnlyOrderExecutionState
    projection: OnlyOrderExecutionProjection
    event_intents: tuple[OnlyExecutionEventIntent, ...]
    terminal_fill: bool


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
        allowed = {
            OnlyOrderStatus.SUBMITTED,
            OnlyOrderStatus.ACCEPTED,
            OnlyOrderStatus.PARTIALLY_FILLED,
            OnlyOrderStatus.PENDING_CANCEL,
        }
        if before.status not in allowed:
            raise ValueError("Order state does not accept a Fill")
        if trade.quantity.precision != before.remaining_quantity.precision:
            raise ValueError("Fill quantity precision disagrees with Order")
        if trade.quantity.value > before.remaining_quantity.value:
            raise ValueError("Fill exceeds Order remaining quantity")
        new_filled_value = before.filled_quantity.value + trade.quantity.value
        new_remaining_value = before.quantity.value - new_filled_value
        cumulative = before.cumulative_price_quantity + trade.price.value * trade.quantity.value
        precision = max(
            trade.price.precision,
            0 if before.price is None else before.price.precision,
            0 if before.average_fill_price is None else before.average_fill_price.precision,
        )
        average = OnlyPrice(
            (cumulative / new_filled_value).quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_EVEN),
            precision,
        )
        terminal = new_remaining_value == 0
        status = (
            OnlyOrderStatus.FILLED
            if terminal
            else (
                OnlyOrderStatus.PENDING_CANCEL
                if before.status is OnlyOrderStatus.PENDING_CANCEL
                else OnlyOrderStatus.PARTIALLY_FILLED
            )
        )
        after = replace(
            before,
            status=status,
            filled_quantity=OnlyQuantity(new_filled_value, before.quantity.precision),
            remaining_quantity=OnlyQuantity(new_remaining_value, before.quantity.precision),
            average_fill_price=average,
            fill_count=before.fill_count + 1,
            cumulative_price_quantity=cumulative,
            last_trade_id=trade.trade_id,
            historical_fill_identity_missing=False,
            updated_at=trade.ts_init,
            filled_at=trade.ts_event if terminal else None,
            version=before.version + 1,
            last_external_sequence=trade.source_sequence,
        )
        builder = OnlyRuntimeProjectionBuilder()
        projection = OnlyOrderExecutionProjection(
            builder.identity(
                component=OnlyRuntimeProjectionComponent.ORDER,
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
            (
                _intent(
                    OnlyRuntimeProjectionComponent.ORDER,
                    "ORDER_FILLED" if terminal else "ORDER_PARTIALLY_FILLED",
                    after.to_dict(),
                ),
            ),
            terminal,
        )


class OnlyPositionTradeReducer:
    def reduce(
        self,
        before: OnlyPositionExecutionState | None,
        trade: OnlyPlannedTrade,
        creation: OnlyPositionCreationAuthority | None,
        position_reservation: OnlyPositionReservationExecutionState | None = None,
        close_authority: OnlyAttributedCloseCostAuthority | None = None,
        *,
        cycle: int,
        projection_sequence: int,
    ) -> OnlyPositionTradeReduction:
        if trade.position_effect is OnlyPositionEffect.CLOSE:
            if before is None or position_reservation is None:
                raise ValueError("CLOSE_POSITION_REQUIRED")
            if before.status is not OnlyPositionStatus.OPEN or before.average_open_price is None:
                raise ValueError("CLOSE_POSITION_REQUIRED")
            account_hold = (
                trade.quantity.value
                if position_reservation.stage
                in {OnlyPositionReservationStage.LOCAL_ONLY, OnlyPositionReservationStage.SENT_TO_BROKER}
                else Decimal(0)
            )
            local_available = max(
                before.settled_quantity.value
                - before.order_frozen_quantity.value
                - before.risk_reserved_quantity.value
                - before.restricted_quantity.value,
                Decimal(0),
            )
            if before.broker_available_quantity is not None:
                local_available = min(local_available, before.broker_available_quantity.value)
            if (
                trade.quantity.value > before.total_quantity.value
                or trade.quantity.value > local_available + account_hold
                or account_hold > before.risk_reserved_quantity.value
            ):
                raise ValueError("CLOSE_POSITION_INSUFFICIENT")
            if (
                close_authority is None
                or close_authority.position_id != before.position_id
                or close_authority.position_quantity_before != before.total_quantity
                or close_authority.position_cumulative_cost_before != before.cumulative_open_price_quantity
                or close_authority.fill_quantity != trade.quantity
            ):
                raise ValueError("CLOSE_COST_AUTHORITY_POSITION_CONFLICT")
            quantity_after = close_authority.position_quantity_after.value
            cumulative_after = close_authority.position_cumulative_cost_after
            currency = trade.authoritative_fee.currency
            realized = close_authority.realized_pnl_delta
            if realized.currency != currency:
                raise ValueError("CLOSE_COST_AUTHORITY_CURRENCY_CONFLICT")
            after = replace(
                before,
                status=(OnlyPositionStatus.CLOSED if quantity_after == 0 else OnlyPositionStatus.OPEN),
                total_quantity=OnlyQuantity(quantity_after, before.total_quantity.precision),
                settled_quantity=OnlyQuantity(
                    before.settled_quantity.value - trade.quantity.value,
                    before.settled_quantity.precision,
                ),
                risk_reserved_quantity=OnlyQuantity(
                    before.risk_reserved_quantity.value - account_hold,
                    before.risk_reserved_quantity.precision,
                ),
                average_open_price=close_authority.position_average_open_price_after,
                realized_pnl=before.realized_pnl + realized,
                fees=before.fees + trade.authoritative_fee,
                updated_at=trade.ts_event,
                closed_at=trade.ts_event if quantity_after == 0 else None,
                version=before.version + 1,
                last_trade_sequence=trade.source_sequence,
                last_trade_order=trade.stable_order,
                cumulative_open_price_quantity=cumulative_after,
            )
            builder = OnlyRuntimeProjectionBuilder()
            projection = OnlyPositionExecutionProjection(
                builder.identity(
                    component=OnlyRuntimeProjectionComponent.POSITION,
                    entity_key=str(after.position_id),
                    before=before,
                    after=after,
                    projection_sequence=projection_sequence,
                ),
                before,
                after,
                realized,
                OnlyPositionExecutionReplayMetadata(cycle),
            )
            projection = builder.finalize(projection)
            assert isinstance(projection, OnlyPositionExecutionProjection)
            return OnlyPositionTradeReduction(
                after,
                projection,
                realized,
                (
                    _intent(
                        OnlyRuntimeProjectionComponent.POSITION,
                        "POSITION_CLOSED" if quantity_after == 0 else "POSITION_DECREASED",
                        after.to_dict(),
                    ),
                ),
            )
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
            cumulative_before = Decimal(0)
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
            cumulative_before = before.cumulative_open_price_quantity
        total_value = total_before.value + trade.quantity.value
        cumulative = cumulative_before + trade.price.value * trade.quantity.value
        average = _average_open_price(cumulative, total_value, trade.price.precision, average_before)
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
            cumulative,
        )
        zero = OnlyMoney(Decimal(0), trade.authoritative_fee.currency)
        builder = OnlyRuntimeProjectionBuilder()
        projection = OnlyPositionExecutionProjection(
            builder.identity(
                component=OnlyRuntimeProjectionComponent.POSITION,
                entity_key=str(after.position_id),
                before=before,
                after=after,
                projection_sequence=projection_sequence,
            ),
            before,
            after,
            zero,
            OnlyPositionExecutionReplayMetadata(creation.cycle if before is None and creation is not None else cycle),
        )
        projection = builder.finalize(projection)
        assert isinstance(projection, OnlyPositionExecutionProjection)
        event_type = "POSITION_OPENED" if before is None else "POSITION_INCREASED"
        return OnlyPositionTradeReduction(
            after,
            projection,
            zero,
            (_intent(OnlyRuntimeProjectionComponent.POSITION, event_type, after.to_dict()),),
        )


class OnlyAllocationTradeReducer:
    def reduce(
        self,
        before: OnlyAllocationExecutionState | None,
        trade: OnlyPlannedTrade,
        creation: OnlyAllocationCreationAuthority | None,
        position_reservation: OnlyPositionReservationExecutionState | None = None,
        close_authority: OnlyAttributedCloseCostAuthority | None = None,
        *,
        cycle: int,
        projection_sequence: int,
    ) -> OnlyAllocationTradeReduction:
        if trade.position_effect is OnlyPositionEffect.CLOSE:
            if before is None or position_reservation is None or before.average_open_price is None:
                raise ValueError("CLOSE_ALLOCATION_REQUIRED")
            own_hold = min(position_reservation.remaining_quantity.value, before.risk_reserved_quantity.value)
            available = max(
                before.settled_quantity.value
                - before.order_frozen_quantity.value
                - before.risk_reserved_quantity.value
                - before.restricted_quantity.value,
                Decimal(0),
            )
            if (
                trade.quantity.value > before.total_quantity.value
                or trade.quantity.value > available + own_hold
                or own_hold < trade.quantity.value
            ):
                raise ValueError("CLOSE_ALLOCATION_INSUFFICIENT")
            if (
                close_authority is None
                or close_authority.allocation_id != before.allocation_id
                or close_authority.allocation_quantity_before != before.total_quantity
                or close_authority.allocation_cumulative_cost_before != before.cumulative_open_price_quantity
                or close_authority.fill_quantity != trade.quantity
            ):
                raise ValueError("CLOSE_COST_AUTHORITY_ALLOCATION_CONFLICT")
            quantity_after = close_authority.allocation_quantity_after.value
            cumulative_after = close_authority.allocation_cumulative_cost_after
            realized_pnl_delta = close_authority.realized_pnl_delta
            after = replace(
                before,
                total_quantity=OnlyQuantity(quantity_after, before.total_quantity.precision),
                settled_quantity=OnlyQuantity(
                    before.settled_quantity.value - trade.quantity.value,
                    before.settled_quantity.precision,
                ),
                risk_reserved_quantity=OnlyQuantity(
                    before.risk_reserved_quantity.value - trade.quantity.value,
                    before.risk_reserved_quantity.precision,
                ),
                average_open_price=close_authority.allocation_average_open_price_after,
                realized_pnl=before.realized_pnl + realized_pnl_delta,
                fees=before.fees + trade.authoritative_fee,
                updated_at=trade.ts_event,
                closed_at=trade.ts_event if quantity_after == 0 else None,
                version=before.version + 1,
                last_trade_sequence=trade.source_sequence,
                last_trade_order=trade.stable_order,
                cumulative_open_price_quantity=cumulative_after,
            )
            builder = OnlyRuntimeProjectionBuilder()
            projection = OnlyAllocationExecutionProjection(
                builder.identity(
                    component=OnlyRuntimeProjectionComponent.ALLOCATION,
                    entity_key=str(after.allocation_id),
                    before=before,
                    after=after,
                    projection_sequence=projection_sequence,
                ),
                before,
                after,
                realized_pnl_delta,
                OnlyAllocationExecutionReplayMetadata(cycle),
            )
            projection = builder.finalize(projection)
            assert isinstance(projection, OnlyAllocationExecutionProjection)
            return OnlyAllocationTradeReduction(after, projection, realized_pnl_delta)
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
            cumulative_before = Decimal(0)
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
            cumulative_before = before.cumulative_open_price_quantity
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
            _average_open_price(
                cumulative_before + trade.price.value * trade.quantity.value,
                total_before.value + trade.quantity.value,
                trade.price.precision,
                average_before,
            ),
            realized_before,
            fees_before + trade.authoritative_fee,
            opened_at,
            trade.ts_event,
            None,
            version,
            trade.source_sequence,
            trade.stable_order,
            cumulative_before + trade.price.value * trade.quantity.value,
        )
        builder = OnlyRuntimeProjectionBuilder()
        projection = OnlyAllocationExecutionProjection(
            builder.identity(
                component=OnlyRuntimeProjectionComponent.ALLOCATION,
                entity_key=str(after.allocation_id),
                before=before,
                after=after,
                projection_sequence=projection_sequence,
            ),
            before,
            after,
            zero_money,
            OnlyAllocationExecutionReplayMetadata(creation.cycle if before is None and creation is not None else cycle),
        )
        projection = builder.finalize(projection)
        assert isinstance(projection, OnlyAllocationExecutionProjection)
        return OnlyAllocationTradeReduction(after, projection, zero_money)


class OnlySettlementTradeReducer:
    def reduce(
        self,
        before: OnlySettlementExecutionState | None,
        instruction: OnlySettlementInstruction,
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
            flags_before[0] or trading_day >= instruction.schedule.asset_trade_available_on,
            flags_before[1] or trading_day >= instruction.schedule.cash_trade_available_on,
            flags_before[2] or trading_day >= instruction.schedule.cash_withdrawable_on,
            flags_before[3] or trading_day >= instruction.schedule.legal_settlement_on,
        )
        after = OnlySettlementExecutionState(
            str(instruction.instruction_id),
            trade.account_id,
            trade.instrument_id,
            trade.order_id,
            str(instruction.trade_id),
            instruction.trade_quantity.value,
            instruction.gross_notional,
            *flags_after,
            instruction.schedule.asset_trade_available_on,
            instruction.schedule.cash_trade_available_on,
            instruction.schedule.cash_withdrawable_on,
            instruction.schedule.legal_settlement_on,
            (1 if before is None else before.version) + int(flags_before != flags_after),
            record_sequence + int(flags_before != flags_after),
            instruction,
        )
        records: tuple[OnlySettlementRecordReplay, ...] = ()
        if flags_before != flags_after:
            records = (
                OnlySettlementRecordReplay(
                    str(instruction.instruction_id),
                    after.account_id,
                    after.instrument_id,
                    after.source_order_id,
                    after.source_trade_id,
                    trading_day,
                    instruction.trade_quantity.value if flags_after[0] else Decimal(0),
                    instruction.cash_leg.account_availability_amount
                    if flags_after[1]
                    else _money(Decimal(0), currency),
                    instruction.cash_leg.account_availability_amount
                    if flags_after[2]
                    else _money(Decimal(0), currency),
                    flags_after[3],
                    record_sequence + 1,
                ),
            )
        builder = OnlyRuntimeProjectionBuilder()
        projection = OnlySettlementExecutionProjection(
            builder.identity(
                component=OnlyRuntimeProjectionComponent.SETTLEMENT,
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
            else (_intent(OnlyRuntimeProjectionComponent.SETTLEMENT, "SETTLEMENT_UPDATED", after.to_dict()),)
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
            record_sequence + len(records),
        )
        builder = OnlyRuntimeProjectionBuilder()
        projection = OnlyFeeExecutionProjection(
            builder.identity(
                component=OnlyRuntimeProjectionComponent.FEE,
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
        intents = () if not records else (_intent(OnlyRuntimeProjectionComponent.FEE, "FEE_RECORDED", after.to_dict()),)
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
            valuation_time=trade.ts_init,
            cash=account_cash,
            position_market_value=position_market_value,
            unrealized_pnl=unrealized_pnl,
            equity=account_cash + position_market_value,
            version=before.version + 1,
        )
        builder = OnlyRuntimeProjectionBuilder()
        projection = OnlyValuationExecutionProjection(
            builder.identity(
                component=OnlyRuntimeProjectionComponent.VALUATION,
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
    cumulative: Decimal, total_quantity: Decimal, fill_precision: int, before_price: OnlyPrice | None
) -> OnlyPrice:
    raw = cumulative / total_quantity
    precision = max(fill_precision, 0 if before_price is None else before_price.precision)
    return OnlyPrice(raw.quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_EVEN), precision)


def _money(amount: Decimal, currency: OnlyCurrency) -> OnlyMoney:
    quantum = Decimal(1).scaleb(-currency.precision)
    return OnlyMoney(amount.quantize(quantum), currency)


def _intent(component: OnlyRuntimeProjectionComponent, event_type: str, payload: object) -> OnlyExecutionEventIntent:
    return OnlyExecutionEventIntent(
        component, OnlyEventType(event_type), payload, OnlyEventSource("execution.trade_planner")
    )


__all__ = [name for name in globals() if name.startswith("Only")]
