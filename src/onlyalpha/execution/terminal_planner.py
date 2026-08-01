"""Pure durable planner for Generic T0 Cash Long Close terminal operations."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from onlyalpha.broker.updates import OnlyBrokerOrderRejectedUpdate
from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.value import OnlyMoney, OnlyQuantity
from onlyalpha.event.model import OnlyEvent, OnlyEventSource, OnlyEventType
from onlyalpha.position.enums import (
    OnlyPositionReservationStage,
    OnlyPositionReservationState,
)
from onlyalpha.risk.enums import OnlyRiskReleaseReason, OnlyRiskReservationState

from .capability import OnlyExecutionCapability, only_resolve_execution_capability
from .enums import OnlyExecutionOperationKind
from .event_identity import OnlyExecutionTransactionEventFactory
from .planning_context import OnlyTerminalExecutionPlanningContext
from .projection import (
    OnlyExecutionProjection,
    OnlyExecutionProjectionComponent,
    OnlyOrderTerminalExecutionProjection,
    OnlyPositionReservationExecutionProjection,
    OnlyRiskExecutionProjection,
    OnlyRiskReservationExecutionProjection,
)
from .projection_builder import OnlyExecutionProjectionBuilder
from .terminal_fact import OnlyCommittedTerminalExecutionFactDraft
from .transaction import OnlyExecutionPrecondition, OnlyPreparedExecutionTransaction


class OnlyTerminalExecutionTransactionPlanner:
    """Compile one Long Close terminal update into the shared transaction protocol."""

    def prepare(self, context: OnlyTerminalExecutionPlanningContext) -> OnlyPreparedExecutionTransaction:
        self._validate(context)
        authority = context.terminal_authority
        update = context.update
        terminal_status = authority.terminal_status
        reason, release_reason = _terminal_reasons(context)

        order_after = replace(
            context.order_before,
            status=terminal_status,
            updated_at=update.ts_event,
            cancelled_at=(
                update.ts_event if terminal_status is OnlyOrderStatus.CANCELLED else context.order_before.cancelled_at
            ),
            rejected_at=(
                update.ts_event if terminal_status is OnlyOrderStatus.REJECTED else context.order_before.rejected_at
            ),
            expired_at=(
                update.ts_event if terminal_status is OnlyOrderStatus.EXPIRED else context.order_before.expired_at
            ),
            rejection=(
                update.rejection
                if isinstance(update, OnlyBrokerOrderRejectedUpdate)
                else context.order_before.rejection
            ),
            version=context.order_before.version + 1,
            last_external_sequence=update.source_sequence,
        )
        position_before = context.position_reservation_before
        if position_before.consumed_quantity is None or position_before.released_quantity is None:
            raise ValueError("Terminal Position Reservation authority is incomplete")
        position_release = position_before.remaining_quantity
        position_after = replace(
            position_before,
            remaining_quantity=_zero_quantity(position_before.quantity),
            released_quantity=OnlyQuantity(
                position_before.released_quantity.value + position_release.value,
                position_before.quantity.precision,
            ),
            stage=OnlyPositionReservationStage.RELEASED,
            state=OnlyPositionReservationState.RELEASED,
            updated_at=update.ts_init,
            version=position_before.version + 1,
        )
        risk_before = context.risk_reservation_before
        if risk_before.released_quantity is None:
            raise ValueError("Terminal Risk Reservation released authority is incomplete")
        risk_release_quantity = risk_before.remaining_quantity
        risk_release_notional = risk_before.remaining_notional
        risk_after = replace(
            risk_before,
            remaining_quantity=_zero_quantity(risk_before.reserved_quantity),
            remaining_notional=(
                None
                if risk_before.reserved_notional is None
                else OnlyMoney(
                    risk_before.reserved_notional.amount - risk_before.reserved_notional.amount,
                    risk_before.reserved_notional.currency,
                )
            ),
            released_quantity=OnlyQuantity(
                risk_before.released_quantity.value + risk_release_quantity.value,
                risk_before.reserved_quantity.precision,
            ),
            released_notional=(
                None
                if risk_before.reserved_notional is None
                else OnlyMoney(
                    (Decimal(0) if risk_before.released_notional is None else risk_before.released_notional.amount)
                    + (Decimal(0) if risk_release_notional is None else risk_release_notional.amount),
                    risk_before.reserved_notional.currency,
                )
            ),
            state=OnlyRiskReservationState.RELEASED,
            release_reason=release_reason,
            updated_at=update.ts_init,
            version=risk_before.version + 1,
        )
        risk_snapshot_before = context.risk_before
        released_notional_amount = Decimal(0) if risk_release_notional is None else risk_release_notional.amount
        reserved_notional_after = risk_snapshot_before.reserved_notional
        remaining_notional_after = risk_snapshot_before.remaining_order_notional
        if reserved_notional_after is not None:
            reserved_notional_after = OnlyMoney(
                reserved_notional_after.amount - released_notional_amount,
                reserved_notional_after.currency,
            )
        if remaining_notional_after is not None:
            remaining_notional_after = OnlyMoney(
                remaining_notional_after.amount - released_notional_amount,
                remaining_notional_after.currency,
            )
        risk_snapshot_after = replace(
            risk_snapshot_before,
            ts_event=update.ts_init,
            ts_init=update.ts_init,
            active_order_count=risk_snapshot_before.active_order_count - 1,
            cluster_active_order_count=risk_snapshot_before.cluster_active_order_count - 1,
            reserved_quantity=risk_snapshot_before.reserved_quantity - risk_release_quantity.value,
            reserved_notional=reserved_notional_after,
            remaining_order_notional=remaining_notional_after,
            version=risk_snapshot_before.version + 1,
        )

        builder = OnlyExecutionProjectionBuilder()
        projections: tuple[OnlyExecutionProjection, ...] = (
            builder.finalize(
                OnlyOrderTerminalExecutionProjection(
                    builder.identity(
                        component=OnlyExecutionProjectionComponent.ORDER,
                        entity_key=str(order_after.order_id),
                        before=context.order_before,
                        after=order_after,
                        projection_sequence=1,
                    ),
                    context.order_before,
                    order_after,
                    update.update_id,
                    authority.terminal_identity,
                    terminal_status,
                    reason,
                )
            ),
            builder.finalize(
                OnlyPositionReservationExecutionProjection(
                    builder.identity(
                        component=OnlyExecutionProjectionComponent.POSITION_RESERVATION,
                        entity_key=str(position_after.reservation_id),
                        before=position_before,
                        after=position_after,
                        projection_sequence=2,
                    ),
                    position_before,
                    position_after,
                )
            ),
            builder.finalize(
                OnlyRiskReservationExecutionProjection(
                    builder.identity(
                        component=OnlyExecutionProjectionComponent.RISK_RESERVATION,
                        entity_key=str(risk_after.reservation_id),
                        before=risk_before,
                        after=risk_after,
                        projection_sequence=3,
                    ),
                    risk_before,
                    risk_after,
                )
            ),
            builder.finalize(
                OnlyRiskExecutionProjection(
                    builder.identity(
                        component=OnlyExecutionProjectionComponent.RISK,
                        entity_key=str(risk_snapshot_after.cluster_id),
                        before=risk_snapshot_before,
                        after=risk_snapshot_after,
                        projection_sequence=4,
                    ),
                    risk_snapshot_before,
                    risk_snapshot_after,
                )
            ),
        )
        fact = OnlyCommittedTerminalExecutionFactDraft(
            operation_kind=OnlyExecutionOperationKind.ORDER_TERMINAL,
            terminal_identity=authority.terminal_identity,
            terminal_payload_fingerprint=authority.payload_fingerprint,
            broker_update_id=update.update_id,
            runtime_id=update.runtime_id,
            gateway_id=update.gateway_id,
            account_id=update.account_id,
            cluster_id=context.order_before.cluster_id,
            instrument_id=context.order_before.instrument_id,
            order_id=update.order_id,
            source_sequence=update.source_sequence,
            processing_sequence=context.processing_sequence,
            correlation_id=update.correlation_id,
            causation_id=update.causation_id,
            ts_event=update.ts_event,
            ts_init=update.ts_init,
            terminal_status=terminal_status,
            terminal_reason=reason,
            risk_release_reason=release_reason,
            filled_quantity_before=context.order_before.filled_quantity,
            order_remaining_quantity=context.order_before.remaining_quantity,
            position_reservation_consumed_before=position_before.consumed_quantity,
            position_reservation_released_delta=position_release,
            position_reservation_remaining_after=position_after.remaining_quantity,
            risk_reservation_consumed_quantity_before=risk_before.consumed_quantity,
            risk_reservation_released_quantity_delta=risk_release_quantity,
            risk_reservation_released_notional_delta=risk_release_notional,
            risk_reservation_remaining_quantity_after=risk_after.remaining_quantity,
            active_order_count_delta=-1,
            cluster_active_order_count_delta=-1,
        )
        preconditions = tuple(
            OnlyExecutionPrecondition(
                item.identity.component,
                item.identity.entity_key,
                item.identity.expected_version,
                item.identity.expected_state_hash,
            )
            for item in projections
        )
        events = _events(context, authority.terminal_identity, projections)
        return OnlyPreparedExecutionTransaction(
            transaction_id=authority.terminal_identity,
            runtime_id=update.runtime_id,
            gateway_id=update.gateway_id,
            account_id=update.account_id,
            broker_update_id=update.update_id,
            trade_id=None,
            source_sequence=update.source_sequence,
            prepared_at=context.prepared_at,
            fact_draft=fact,
            projections=projections,
            outbox_events=events,
            preconditions=preconditions,
            operation_kind=OnlyExecutionOperationKind.ORDER_TERMINAL,
            terminal_identity=authority.terminal_identity,
        )

    @staticmethod
    def _validate(context: OnlyTerminalExecutionPlanningContext) -> None:
        update = context.update
        order = context.order_before
        scope = context.position_scope
        capability = only_resolve_execution_capability(
            operation_kind=OnlyExecutionOperationKind.ORDER_TERMINAL,
            market_profile_id=context.market_profile_id,
            account_type=context.account_type,
            order_type=order.order_type,
            order_side=order.side,
            offset=order.offset,
            position_side=scope.position_side,
            position_effect=scope.position_effect,
            position_mode=scope.position_mode,
            has_margin=context.margin_reservation_present,
            account_ledger_parity=context.account_ledger_parity,
        )
        if capability is not OnlyExecutionCapability.DURABLE_TERMINAL:
            raise ValueError(f"terminal execution capability is {capability.value}")
        if update.order_id != order.order_id or update.runtime_id != order.runtime_id:
            raise ValueError("Terminal update scope disagrees with Order")
        if update.account_id != order.account_id or scope.cluster_id != order.cluster_id:
            raise ValueError("Terminal update Account/Cluster scope disagrees")
        if context.terminal_authority.terminal_status is OnlyOrderStatus.CANCELLED:
            allowed = {
                OnlyOrderStatus.SUBMITTED,
                OnlyOrderStatus.ACCEPTED,
                OnlyOrderStatus.PARTIALLY_FILLED,
                OnlyOrderStatus.PENDING_CANCEL,
            }
        elif context.terminal_authority.terminal_status is OnlyOrderStatus.REJECTED:
            allowed = {
                OnlyOrderStatus.SUBMITTED,
                OnlyOrderStatus.ACCEPTED,
                OnlyOrderStatus.PARTIALLY_FILLED,
                OnlyOrderStatus.PENDING_CANCEL,
            }
        else:
            allowed = {
                OnlyOrderStatus.ACCEPTED,
                OnlyOrderStatus.PARTIALLY_FILLED,
                OnlyOrderStatus.PENDING_CANCEL,
            }
        if order.status not in allowed:
            raise ValueError("Order state does not accept this terminal operation")
        if order.last_external_sequence is not None and update.source_sequence <= order.last_external_sequence:
            raise ValueError("Terminal Broker sequence must advance")
        position = context.position_reservation_before
        risk = context.risk_reservation_before
        if position.order_id != order.order_id or position.remaining_quantity != order.remaining_quantity:
            raise ValueError("Position Reservation remaining authority disagrees with Order")
        if position.state not in {
            OnlyPositionReservationState.ACTIVE,
            OnlyPositionReservationState.PARTIALLY_CONSUMED,
        }:
            raise ValueError("Position Reservation is already terminal")
        if risk.order_id != order.order_id or risk.remaining_quantity != order.remaining_quantity:
            raise ValueError("Risk Reservation remaining authority disagrees with Order")
        if risk.state is not OnlyRiskReservationState.ACTIVE:
            raise ValueError("Risk Reservation is already terminal")
        if (
            context.account_cash_reservation_present
            or context.strategy_cash_reservation_present
            or context.margin_reservation_present
        ):
            raise ValueError("Long Close terminal operation forbids Cash and Margin Reservations")
        if context.risk_before.active_order_count < 1 or context.risk_before.cluster_active_order_count < 1:
            raise ValueError("Terminal Risk active Order count would underflow")
        if context.risk_before.reserved_quantity < risk.remaining_quantity.value:
            raise ValueError("Terminal Risk reserved quantity would underflow")


def _terminal_reasons(
    context: OnlyTerminalExecutionPlanningContext,
) -> tuple[str, OnlyRiskReleaseReason]:
    update = context.update
    status = context.terminal_authority.terminal_status
    if isinstance(update, OnlyBrokerOrderRejectedUpdate):
        return f"{update.rejection.code}: {update.rejection.message}", OnlyRiskReleaseReason.ORDER_REJECTED
    if status is OnlyOrderStatus.CANCELLED:
        return update.metadata.get("reason", "ORDER_CANCELLED"), OnlyRiskReleaseReason.ORDER_CANCELLED
    return update.metadata.get("reason", "ORDER_EXPIRED"), OnlyRiskReleaseReason.ORDER_EXPIRED


def _zero_quantity(authority: OnlyQuantity) -> OnlyQuantity:
    return OnlyQuantity(Decimal(0), authority.precision)


def _events(
    context: OnlyTerminalExecutionPlanningContext,
    transaction_id: str,
    projections: tuple[OnlyExecutionProjection, ...],
) -> tuple[OnlyEvent, ...]:
    factory = OnlyExecutionTransactionEventFactory()
    return tuple(
        factory.create(
            transaction_id=transaction_id,
            event_sequence=index,
            event_type=OnlyEventType(f"{projection.identity.component.value}_TERMINAL_APPLIED"),
            timestamp=context.update.ts_event.to_datetime(),
            engine_id=context.engine_id,
            runtime_id=context.update.runtime_id,
            cluster_id=context.order_before.cluster_id,
            source=OnlyEventSource("execution.terminal_planner"),
            payload={
                "terminal_identity": transaction_id,
                "terminal_status": context.terminal_authority.terminal_status.value,
                "component": projection.identity.component.value,
            },
            ts_init=context.update.ts_init.to_datetime(),
            metadata={"broker_update_id": str(context.update.update_id)},
        )
        for index, projection in enumerate(projections, start=1)
    )


__all__ = ["OnlyTerminalExecutionTransactionPlanner"]
