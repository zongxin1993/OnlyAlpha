"""Pure order-level fee accrual reduction."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.domain.value import OnlyMoney, OnlyQuantity
from onlyalpha.event.model import OnlyEventSource, OnlyEventType
from onlyalpha.fee.accrual import OnlyOrderFeeAccrualExecutionState, OnlyOrderFeeComponentAccrual
from onlyalpha.fee.models import OnlyFeeBreakdown, OnlyFeeCalculationScope, OnlyFeeComponent, OnlyFeeInstruction

from ..planned_trade import OnlyPlannedTrade
from ..planning_results import OnlyExecutionEventIntent
from ..projection import (
    OnlyExecutionProjectionComponent,
    OnlyOrderFeeAccrualExecutionProjection,
)
from ..projection_builder import OnlyExecutionProjectionBuilder


@dataclass(frozen=True, slots=True)
class OnlyOrderFeeAccrualTradeReduction:
    before: OnlyOrderFeeAccrualExecutionState | None
    after: OnlyOrderFeeAccrualExecutionState
    incremental_breakdown: OnlyFeeBreakdown
    incremental_total: OnlyMoney
    projection: OnlyOrderFeeAccrualExecutionProjection
    event_intents: tuple[OnlyExecutionEventIntent, ...]


class OnlyOrderFeeAccrualTradeReducer:
    def reduce(
        self,
        before: OnlyOrderFeeAccrualExecutionState | None,
        instruction: OnlyFeeInstruction,
        trade: OnlyPlannedTrade,
        *,
        projection_sequence: int,
    ) -> OnlyOrderFeeAccrualTradeReduction:
        currency = instruction.fee_breakdown.currency
        previous = {} if before is None else {item.key: item for item in before.components}
        components: list[OnlyOrderFeeComponentAccrual] = []
        incremental: list[OnlyFeeComponent] = []
        for target in instruction.fee_breakdown.components:
            prior = previous.pop(target.unique_key, None)
            charged_before = Decimal(0) if prior is None else prior.cumulative_charged_amount.amount
            raw_before = Decimal(0) if prior is None else prior.cumulative_raw_amount.amount
            target_before = Decimal(0) if prior is None else prior.cumulative_target_amount.amount
            raw = Decimal(str(target.metadata.get("raw_amount", target.amount.amount)))
            if target.calculation_scope is OnlyFeeCalculationScope.FILL:
                delta = target.amount.amount
                raw_after = raw_before + raw
                target_after = target_before + target.amount.amount
            else:
                delta = target.amount.amount - charged_before
                raw_after = raw
                target_after = target.amount.amount
            if delta < 0:
                raise ValueError("FEE_ACCRUAL_NEGATIVE_INCREMENT")
            charged_after = charged_before + delta
            components.append(
                OnlyOrderFeeComponentAccrual(
                    target.fee_type,
                    target.authority,
                    target.source_id,
                    target.schedule_id,
                    target.schedule_version,
                    target.calculation_scope,
                    OnlyMoney(raw_after, currency),
                    OnlyMoney(target_after, currency),
                    OnlyMoney(charged_after, currency),
                )
            )
            if delta:
                incremental.append(
                    OnlyFeeComponent(
                        target.fee_type,
                        target.authority,
                        OnlyMoney(delta, currency),
                        target.status,
                        target.source_id,
                        target.schedule_id,
                        target.schedule_version,
                        target.effective_date,
                        target.metadata,
                        target.calculation_scope,
                    )
                )
        components.extend(previous.values())
        components_tuple = tuple(sorted(components, key=lambda item: tuple(str(value) for value in item.key)))
        incremental_tuple = tuple(incremental)
        incremental_total = OnlyMoney(sum((item.amount.amount for item in incremental_tuple), Decimal(0)), currency)
        breakdown = OnlyFeeBreakdown(currency, incremental_tuple, incremental_total, instruction.fee_breakdown.status)
        cumulative_quantity = (
            trade.quantity
            if before is None
            else OnlyQuantity(
                before.cumulative_fill_quantity.value + trade.quantity.value,
                before.cumulative_fill_quantity.precision,
            )
        )
        cumulative_notional = (
            trade.gross_notional if before is None else before.cumulative_fill_notional + trade.gross_notional
        )
        after = OnlyOrderFeeAccrualExecutionState(
            trade.runtime_id,
            trade.account_id,
            trade.cluster_id,
            trade.order_id,
            currency,
            cumulative_quantity,
            cumulative_notional,
            OnlyMoney(sum((item.cumulative_charged_amount.amount for item in components_tuple), Decimal(0)), currency),
            components_tuple,
            1 if before is None else before.fill_count + 1,
            trade.trade_id,
            trade.ts_init,
            1 if before is None else before.version + 1,
        )
        builder = OnlyExecutionProjectionBuilder()
        projection = OnlyOrderFeeAccrualExecutionProjection(
            builder.identity(
                component=OnlyExecutionProjectionComponent.ORDER_FEE_ACCRUAL,
                entity_key=str(trade.order_id),
                before=before,
                after=after,
                projection_sequence=projection_sequence,
            ),
            before,
            after,
        )
        projection = builder.finalize(projection)
        assert isinstance(projection, OnlyOrderFeeAccrualExecutionProjection)
        intent = OnlyExecutionEventIntent(
            OnlyExecutionProjectionComponent.ORDER_FEE_ACCRUAL,
            OnlyEventType("ORDER_FEE_ACCRUAL_UPDATED"),
            after.to_dict(),
            OnlyEventSource("execution.trade_planner"),
        )
        return OnlyOrderFeeAccrualTradeReduction(before, after, breakdown, incremental_total, projection, (intent,))


__all__ = ["OnlyOrderFeeAccrualTradeReducer", "OnlyOrderFeeAccrualTradeReduction"]
