"""Pure durable planner for Broker Order Accepted operations."""

from __future__ import annotations

from decimal import Decimal

from onlyalpha.domain.value import OnlyMoney
from onlyalpha.event.model import OnlyEvent, OnlyEventSource, OnlyEventType
from onlyalpha.market.models import OnlyPositionEffect
from onlyalpha.transaction.enums import OnlyRuntimeOperationKind
from onlyalpha.transaction.event_identity import OnlyExecutionTransactionEventFactory
from onlyalpha.transaction.projection import (
    OnlyOrderAcceptedExecutionProjection,
    OnlyPositionExecutionProjection,
    OnlyPositionExecutionReplayMetadata,
    OnlyPositionReservationExecutionProjection,
    OnlyRuntimeProjection,
    OnlyRuntimeProjectionComponent,
    OnlyStrategyCashReservationExecutionProjection,
    OnlyStrategyLedgerExecutionProjection,
)
from onlyalpha.transaction.projection_builder import OnlyRuntimeProjectionBuilder
from onlyalpha.transaction.transaction import OnlyPreparedRuntimeTransaction, OnlyRuntimePrecondition

from .accepted_fact import OnlyCommittedOrderAcceptedFactDraft
from .capability import OnlyExecutionCapability
from .lifecycle_reducers import (
    only_reduce_order_accepted,
    only_reduce_position_hold_release,
    only_reduce_position_reservation_acknowledged,
    only_reduce_strategy_cash_reservation_acknowledged,
    only_reduce_strategy_ledger_reservation_acknowledged,
)
from .planning_context import OnlyOrderAcceptedExecutionPlanningContext


class OnlyOrderAcceptedExecutionTransactionPlanner:
    """Compile one normalized Broker Accepted fact into a complete transaction."""

    def prepare(
        self,
        context: OnlyOrderAcceptedExecutionPlanningContext,
    ) -> OnlyPreparedRuntimeTransaction:
        self._validate(context)
        update = context.update
        authority = context.accepted_authority
        builder = OnlyRuntimeProjectionBuilder()
        projections: list[OnlyRuntimeProjection] = []

        order_after = only_reduce_order_accepted(context.order_before, update)
        projections.append(
            builder.finalize(
                OnlyOrderAcceptedExecutionProjection(
                    builder.identity(
                        component=OnlyRuntimeProjectionComponent.ORDER,
                        entity_key=str(order_after.order_id),
                        before=context.order_before,
                        after=order_after,
                        projection_sequence=1,
                    ),
                    context.order_before,
                    order_after,
                    update.update_id,
                    authority.accepted_identity,
                )
            )
        )

        if context.margin_reservation_before is not None:
            pass
        elif context.position_scope.position_effect is OnlyPositionEffect.CLOSE:
            position_before = context.position_before
            reservation_before = context.position_reservation_before
            if position_before is None or reservation_before is None:
                raise ValueError("SELL CLOSE Accepted requires Position and Reservation authority")
            position_after = only_reduce_position_hold_release(
                position_before,
                reservation_before.remaining_quantity,
            )
            projections.append(
                builder.finalize(
                    OnlyPositionExecutionProjection(
                        builder.identity(
                            component=OnlyRuntimeProjectionComponent.POSITION,
                            entity_key=str(position_after.position_id),
                            before=position_before,
                            after=position_after,
                            projection_sequence=len(projections) + 1,
                        ),
                        position_before,
                        position_after,
                        OnlyMoney(Decimal(0), position_before.realized_pnl.currency),
                        OnlyPositionExecutionReplayMetadata(context.position_cycle),
                    )
                )
            )
            position_reservation_after = only_reduce_position_reservation_acknowledged(reservation_before, update)
            projections.append(
                builder.finalize(
                    OnlyPositionReservationExecutionProjection(
                        builder.identity(
                            component=OnlyRuntimeProjectionComponent.POSITION_RESERVATION,
                            entity_key=str(position_reservation_after.reservation_id),
                            before=reservation_before,
                            after=position_reservation_after,
                            projection_sequence=len(projections) + 1,
                        ),
                        reservation_before,
                        position_reservation_after,
                    )
                )
            )
        else:
            cash_reservation_before = context.strategy_cash_reservation_before
            if cash_reservation_before is None:
                raise ValueError("BUY OPEN Accepted requires Strategy cash Reservation authority")
            ledger_after = only_reduce_strategy_ledger_reservation_acknowledged(
                context.strategy_ledger_before,
                update,
            )
            projections.append(
                builder.finalize(
                    OnlyStrategyLedgerExecutionProjection(
                        builder.identity(
                            component=OnlyRuntimeProjectionComponent.STRATEGY_LEDGER,
                            entity_key=str(ledger_after.ledger_id),
                            before=context.strategy_ledger_before,
                            after=ledger_after,
                            projection_sequence=len(projections) + 1,
                        ),
                        context.strategy_ledger_before,
                        ledger_after,
                        context.strategy_valuation_lines,
                    )
                )
            )
            cash_reservation_after = only_reduce_strategy_cash_reservation_acknowledged(cash_reservation_before, update)
            projections.append(
                builder.finalize(
                    OnlyStrategyCashReservationExecutionProjection(
                        builder.identity(
                            component=OnlyRuntimeProjectionComponent.STRATEGY_CASH_RESERVATION,
                            entity_key=str(cash_reservation_after.reservation_id),
                            before=cash_reservation_before,
                            after=cash_reservation_after,
                            projection_sequence=len(projections) + 1,
                        ),
                        cash_reservation_before,
                        cash_reservation_after,
                    )
                )
            )

        frozen = tuple(projections)
        fact = OnlyCommittedOrderAcceptedFactDraft(
            operation_kind=OnlyRuntimeOperationKind.ORDER_ACCEPTED,
            accepted_identity=authority.accepted_identity,
            accepted_payload_fingerprint=authority.payload_fingerprint,
            broker_update_id=update.update_id,
            runtime_id=update.runtime_id,
            gateway_id=update.gateway_id,
            account_id=update.account_id,
            cluster_id=context.order_before.cluster_id,
            instrument_id=context.order_before.instrument_id,
            order_id=update.order_id,
            venue_order_id=update.venue_order_id,
            execution_capability=context.support_decision.capability,
            execution_support_policy_version=context.support_decision.policy_version,
            execution_support_fingerprint=context.support_decision.fingerprint,
            source_sequence=update.source_sequence,
            processing_sequence=context.processing_sequence,
            correlation_id=update.correlation_id,
            causation_id=update.causation_id,
            ts_event=update.ts_event,
            ts_init=update.ts_init,
        )
        preconditions = tuple(
            OnlyRuntimePrecondition(
                item.identity.component,
                item.identity.entity_key,
                item.identity.expected_version,
                item.identity.expected_state_hash,
            )
            for item in frozen
        )
        prepared = OnlyPreparedRuntimeTransaction(
            transaction_id=authority.accepted_identity,
            runtime_id=update.runtime_id,
            operation_kind=OnlyRuntimeOperationKind.ORDER_ACCEPTED,
            operation_identity=authority.accepted_identity,
            account_id=update.account_id,
            effective_time=update.ts_event,
            prepared_at=context.prepared_at,
            fact_draft=fact,
            projections=frozen,
            outbox_events=_events(context, frozen),
            preconditions=preconditions,
        )
        from .economic_invariants import OnlyPreparedExecutionEconomicInvariantValidator

        OnlyPreparedExecutionEconomicInvariantValidator().validate(prepared)
        return prepared

    @staticmethod
    def _validate(context: OnlyOrderAcceptedExecutionPlanningContext) -> None:
        order = context.order_before
        update = context.update
        if context.support_decision.capability is not OnlyExecutionCapability.DURABLE_ORDER_ACCEPTED:
            raise ValueError("Accepted capability routing invariant failed")
        if update.account_id != order.account_id or context.position_scope.cluster_id != order.cluster_id:
            raise ValueError("Accepted Account/Cluster scope disagrees")
        opening = context.position_scope.position_effect is OnlyPositionEffect.OPEN
        closing = context.position_scope.position_effect is OnlyPositionEffect.CLOSE
        if not opening and not closing:
            raise ValueError("Accepted order semantics are unsupported")


def _events(
    context: OnlyOrderAcceptedExecutionPlanningContext,
    projections: tuple[OnlyRuntimeProjection, ...],
) -> tuple[OnlyEvent, ...]:
    factory = OnlyExecutionTransactionEventFactory()
    return tuple(
        factory.create(
            transaction_id=context.accepted_authority.accepted_identity,
            event_sequence=index,
            event_type=OnlyEventType(f"{projection.identity.component.value}_ACCEPTED_APPLIED"),
            timestamp=context.update.ts_event.to_datetime(),
            engine_id=context.engine_id,
            runtime_id=context.update.runtime_id,
            cluster_id=context.order_before.cluster_id,
            source=OnlyEventSource("execution.accepted_planner"),
            payload={
                "accepted_identity": context.accepted_authority.accepted_identity,
                "component": projection.identity.component.value,
                "venue_order_id": str(context.update.venue_order_id),
            },
            ts_init=context.update.ts_init.to_datetime(),
            metadata={"broker_update_id": str(context.update.update_id)},
        )
        for index, projection in enumerate(projections, start=1)
    )


__all__ = ["OnlyOrderAcceptedExecutionTransactionPlanner"]
