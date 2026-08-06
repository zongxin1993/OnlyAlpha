"""Pure order fee target-to-application reduction."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.event.model import OnlyEventSource, OnlyEventType
from onlyalpha.fee.accrual import OnlyOrderFeeAccrualAuthority, OnlyOrderFeeAccrualState
from onlyalpha.fee.application import OnlyFeeApplicationInstruction
from onlyalpha.fee.models import OnlyFeeAssessment
from onlyalpha.transaction.projection import OnlyOrderFeeAccrualProjection, OnlyRuntimeProjectionComponent
from onlyalpha.transaction.projection_builder import OnlyRuntimeProjectionBuilder

from ..planned_trade import OnlyPlannedTrade
from ..planning_results import OnlyExecutionEventIntent


@dataclass(frozen=True, slots=True)
class OnlyOrderFeeAccrualTradeReduction:
    before: OnlyOrderFeeAccrualState | None
    after: OnlyOrderFeeAccrualState
    application: OnlyFeeApplicationInstruction
    projection: OnlyOrderFeeAccrualProjection
    event_intents: tuple[OnlyExecutionEventIntent, ...]


class OnlyOrderFeeAccrualTradeReducer:
    def reduce(
        self,
        before: OnlyOrderFeeAccrualState | None,
        assessment: OnlyFeeAssessment,
        trade: OnlyPlannedTrade,
        *,
        cumulative_fill_quantity: object,
        cumulative_fill_notional: object,
        order_fixed_policy_fingerprint: str,
        projection_sequence: int,
    ) -> OnlyOrderFeeAccrualTradeReduction:
        from onlyalpha.domain.value import OnlyMoney, OnlyQuantity

        if not isinstance(cumulative_fill_quantity, OnlyQuantity) or not isinstance(
            cumulative_fill_notional, OnlyMoney
        ):
            raise TypeError("fee accrual requires typed cumulative Fill authority")
        after, application = OnlyOrderFeeAccrualAuthority().apply(
            before,
            assessment,
            cumulative_fill_quantity=cumulative_fill_quantity,
            cumulative_fill_notional=cumulative_fill_notional,
            updated_at=trade.ts_init,
            order_fixed_policy_fingerprint=order_fixed_policy_fingerprint,
        )
        builder = OnlyRuntimeProjectionBuilder()
        projection = OnlyOrderFeeAccrualProjection(
            builder.identity(
                component=OnlyRuntimeProjectionComponent.ORDER_FEE_ACCRUAL,
                entity_key=str(trade.order_id),
                before=before,
                after=after,
                projection_sequence=projection_sequence,
            ),
            before,
            after,
        )
        projection = builder.finalize(projection)
        assert isinstance(projection, OnlyOrderFeeAccrualProjection)
        intent = OnlyExecutionEventIntent(
            OnlyRuntimeProjectionComponent.ORDER_FEE_ACCRUAL,
            OnlyEventType("ORDER_FEE_ACCRUAL_UPDATED"),
            after.to_dict(),
            OnlyEventSource("execution.trade_planner"),
        )
        return OnlyOrderFeeAccrualTradeReduction(before, after, application, projection, (intent,))


__all__ = ["OnlyOrderFeeAccrualTradeReducer", "OnlyOrderFeeAccrualTradeReduction"]
