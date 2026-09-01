"""Pure durable planner for supported cash-long Order terminal operations."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from onlyalpha.broker.updates import OnlyBrokerOrderRejectedUpdate
from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.event.model import OnlyEvent, OnlyEventSource, OnlyEventType
from onlyalpha.position.enums import OnlyPositionReservationStage
from onlyalpha.risk.enums import OnlyRiskReleaseReason
from onlyalpha.transaction.enums import OnlyRuntimeOperationKind
from onlyalpha.transaction.event_identity import OnlyExecutionTransactionEventFactory
from onlyalpha.transaction.projection import (
    OnlyAccountCashReservationExecutionProjection,
    OnlyAccountExecutionProjection,
    OnlyAllocationExecutionProjection,
    OnlyAllocationExecutionReplayMetadata,
    OnlyMarginReservationExecutionProjection,
    OnlyOrderTerminalExecutionProjection,
    OnlyPositionExecutionProjection,
    OnlyPositionExecutionReplayMetadata,
    OnlyPositionReservationExecutionProjection,
    OnlyRiskExecutionProjection,
    OnlyRiskReservationExecutionProjection,
    OnlyRuntimeProjection,
    OnlyRuntimeProjectionComponent,
    OnlyStrategyCashReservationExecutionProjection,
    OnlyStrategyLedgerExecutionProjection,
)
from onlyalpha.transaction.projection_builder import OnlyRuntimeProjectionBuilder
from onlyalpha.transaction.transaction import OnlyPreparedRuntimeTransaction, OnlyRuntimePrecondition

from .capability import OnlyExecutionCapability
from .execution_state import OnlyMarginReservationExecutionStage, OnlyMarginReservationExecutionStatus
from .lifecycle_reducers import (
    only_reduce_account_cash_reservation_terminal,
    only_reduce_account_terminal_release,
    only_reduce_allocation_hold_release,
    only_reduce_order_terminal,
    only_reduce_position_hold_release,
    only_reduce_position_reservation_terminal,
    only_reduce_risk_reservation_terminal,
    only_reduce_strategy_cash_reservation_terminal,
    only_reduce_strategy_ledger_terminal_release,
    only_reduce_terminal_risk_snapshot,
)
from .planning_context import OnlyTerminalExecutionPlanningContext
from .terminal_fact import OnlyCommittedTerminalExecutionFactDraft, OnlyTerminalEconomicReleaseKind


class OnlyTerminalExecutionTransactionPlanner:
    """Compile BUY OPEN or SELL CLOSE terminal facts into one transaction."""

    def prepare(self, context: OnlyTerminalExecutionPlanningContext) -> OnlyPreparedRuntimeTransaction:
        self._validate(context)
        update = context.update
        authority = context.terminal_authority
        reason, release_reason = _terminal_reasons(context)
        builder = OnlyRuntimeProjectionBuilder()
        projections: list[OnlyRuntimeProjection] = []

        order_after = only_reduce_order_terminal(context.order_before, update, authority)
        projections.append(
            builder.finalize(
                OnlyOrderTerminalExecutionProjection(
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
                    authority.terminal_identity,
                    authority.terminal_status,
                    reason,
                )
            )
        )

        released_cash: OnlyMoney | None = None
        released_margin: OnlyMoney | None = None
        released_quantity = None
        if context.margin_reservation_before is not None:
            margin_before = context.margin_reservation_before
            released_margin = margin_before.remaining_reserved_amount
            remaining_occupied = margin_before.occupied_amount.amount
            margin_after = replace(
                margin_before,
                remaining_reserved_amount=OnlyMoney(Decimal(0), margin_before.currency),
                released_amount=margin_before.released_amount + released_margin,
                state=(
                    OnlyMarginReservationExecutionStatus.OCCUPIED
                    if remaining_occupied > 0
                    else OnlyMarginReservationExecutionStatus.RELEASED
                ),
                stage=(
                    OnlyMarginReservationExecutionStage.OCCUPIED
                    if remaining_occupied > 0
                    else OnlyMarginReservationExecutionStage.RELEASED
                ),
                updated_at=update.ts_init,
                version=margin_before.version + 1,
            )
            account_before = context.account_before
            if (
                account_before.reserved_margin is None
                or account_before.released_margin is None
                or account_before.occupied_margin is None
            ):
                raise ValueError("Margin terminal requires complete Account Margin authority")
            account_after = replace(
                account_before,
                reserved_margin=account_before.reserved_margin - released_margin,
                released_margin=account_before.released_margin + released_margin,
                available_margin=OnlyMoney(
                    account_before.ledger_cash.amount
                    - account_before.order_reserved_cash.amount
                    - account_before.unsettled_receivable_cash.amount
                    - (account_before.reserved_margin.amount - released_margin.amount)
                    - account_before.occupied_margin.amount,
                    account_before.base_currency,
                ),
                updated_at=update.ts_init,
                version=account_before.version + 1,
            )
            projections.append(
                builder.finalize(
                    OnlyAccountExecutionProjection(
                        builder.identity(
                            component=OnlyRuntimeProjectionComponent.ACCOUNT,
                            entity_key=str(account_after.account_id),
                            before=account_before,
                            after=account_after,
                            projection_sequence=len(projections) + 1,
                        ),
                        account_before,
                        account_after,
                    )
                )
            )
            projections.append(
                builder.finalize(
                    OnlyMarginReservationExecutionProjection(
                        builder.identity(
                            component=OnlyRuntimeProjectionComponent.MARGIN_RESERVATION,
                            entity_key=margin_after.reservation_id,
                            before=margin_before,
                            after=margin_after,
                            projection_sequence=len(projections) + 1,
                        ),
                        margin_before,
                        margin_after,
                    )
                )
            )
        elif context.position_scope.position_effect.value == "CLOSE":
            reservation_before = context.position_reservation_before
            allocation_before = context.allocation_before
            if reservation_before is None or allocation_before is None:
                raise ValueError("SELL CLOSE terminal requires Position Reservation and Allocation authority")
            released_quantity = reservation_before.remaining_quantity
            if reservation_before.stage in {
                OnlyPositionReservationStage.LOCAL_ONLY,
                OnlyPositionReservationStage.SENT_TO_BROKER,
            }:
                position_before = context.position_before
                if position_before is None:
                    raise ValueError("unacknowledged SELL CLOSE terminal requires Position authority")
                position_after = only_reduce_position_hold_release(position_before, released_quantity)
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
            allocation_after = only_reduce_allocation_hold_release(allocation_before, released_quantity)
            projections.append(
                builder.finalize(
                    OnlyAllocationExecutionProjection(
                        builder.identity(
                            component=OnlyRuntimeProjectionComponent.ALLOCATION,
                            entity_key=str(allocation_after.allocation_id),
                            before=allocation_before,
                            after=allocation_after,
                            projection_sequence=len(projections) + 1,
                        ),
                        allocation_before,
                        allocation_after,
                        OnlyMoney(Decimal(0), allocation_before.realized_pnl.currency),
                        OnlyAllocationExecutionReplayMetadata(context.allocation_cycle),
                    )
                )
            )
        else:
            account_reservation = context.account_cash_reservation_before
            strategy_reservation = context.strategy_cash_reservation_before
            if account_reservation is None or strategy_reservation is None:
                raise ValueError("BUY OPEN terminal requires both cash Reservation authorities")
            if account_reservation.remaining_amount != strategy_reservation.remaining_amount:
                raise ValueError("Account and Strategy cash release authority differs")
            released_cash = account_reservation.remaining_amount
            account_after = only_reduce_account_terminal_release(
                context.account_before,
                released_cash,
                update.ts_init,
            )
            projections.append(
                builder.finalize(
                    OnlyAccountExecutionProjection(
                        builder.identity(
                            component=OnlyRuntimeProjectionComponent.ACCOUNT,
                            entity_key=str(account_after.account_id),
                            before=context.account_before,
                            after=account_after,
                            projection_sequence=len(projections) + 1,
                        ),
                        context.account_before,
                        account_after,
                    )
                )
            )
            ledger_after = only_reduce_strategy_ledger_terminal_release(
                context.strategy_ledger_before,
                strategy_reservation,
                update.ts_init,
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
            account_reservation_after = only_reduce_account_cash_reservation_terminal(
                account_reservation,
                update.ts_init,
            )
            projections.append(
                builder.finalize(
                    OnlyAccountCashReservationExecutionProjection(
                        builder.identity(
                            component=OnlyRuntimeProjectionComponent.ACCOUNT_CASH_RESERVATION,
                            entity_key=account_reservation_after.reservation_id,
                            before=account_reservation,
                            after=account_reservation_after,
                            projection_sequence=len(projections) + 1,
                        ),
                        account_reservation,
                        account_reservation_after,
                    )
                )
            )
            strategy_reservation_after = only_reduce_strategy_cash_reservation_terminal(
                strategy_reservation,
                update.ts_init,
            )
            projections.append(
                builder.finalize(
                    OnlyStrategyCashReservationExecutionProjection(
                        builder.identity(
                            component=OnlyRuntimeProjectionComponent.STRATEGY_CASH_RESERVATION,
                            entity_key=str(strategy_reservation_after.reservation_id),
                            before=strategy_reservation,
                            after=strategy_reservation_after,
                            projection_sequence=len(projections) + 1,
                        ),
                        strategy_reservation,
                        strategy_reservation_after,
                    )
                )
            )

        if context.position_scope.position_effect.value == "CLOSE":
            position_reservation = context.position_reservation_before
            assert position_reservation is not None
            position_reservation_after = only_reduce_position_reservation_terminal(
                position_reservation,
                update.ts_init,
            )
            projections.append(
                builder.finalize(
                    OnlyPositionReservationExecutionProjection(
                        builder.identity(
                            component=OnlyRuntimeProjectionComponent.POSITION_RESERVATION,
                            entity_key=str(position_reservation_after.reservation_id),
                            before=position_reservation,
                            after=position_reservation_after,
                            projection_sequence=len(projections) + 1,
                        ),
                        position_reservation,
                        position_reservation_after,
                    )
                )
            )

        risk_before = context.risk_reservation_before
        risk_after = only_reduce_risk_reservation_terminal(risk_before, release_reason, update.ts_init)
        projections.append(
            builder.finalize(
                OnlyRiskReservationExecutionProjection(
                    builder.identity(
                        component=OnlyRuntimeProjectionComponent.RISK_RESERVATION,
                        entity_key=str(risk_after.reservation_id),
                        before=risk_before,
                        after=risk_after,
                        projection_sequence=len(projections) + 1,
                    ),
                    risk_before,
                    risk_after,
                )
            )
        )
        risk_snapshot_after = only_reduce_terminal_risk_snapshot(context.risk_before, risk_before, update.ts_init)
        projections.append(
            builder.finalize(
                OnlyRiskExecutionProjection(
                    builder.identity(
                        component=OnlyRuntimeProjectionComponent.RISK,
                        entity_key=str(risk_snapshot_after.cluster_id),
                        before=context.risk_before,
                        after=risk_snapshot_after,
                        projection_sequence=len(projections) + 1,
                    ),
                    context.risk_before,
                    risk_snapshot_after,
                )
            )
        )

        frozen = tuple(projections)
        fact = OnlyCommittedTerminalExecutionFactDraft(
            operation_kind=OnlyRuntimeOperationKind.ORDER_TERMINAL,
            terminal_identity=authority.terminal_identity,
            terminal_payload_fingerprint=authority.payload_fingerprint,
            broker_update_id=update.update_id,
            runtime_id=update.runtime_id,
            gateway_id=update.gateway_id,
            account_id=update.account_id,
            cluster_id=context.order_before.cluster_id,
            instrument_id=context.order_before.instrument_id,
            order_id=update.order_id,
            execution_capability=context.support_decision.capability,
            execution_support_policy_version=context.support_decision.policy_version,
            execution_support_fingerprint=context.support_decision.fingerprint,
            source_sequence=update.source_sequence,
            processing_sequence=context.processing_sequence,
            correlation_id=update.correlation_id,
            causation_id=update.causation_id,
            ts_event=update.ts_event,
            ts_init=update.ts_init,
            terminal_status=authority.terminal_status,
            terminal_reason=reason,
            risk_release_reason=release_reason,
            filled_quantity_before=context.order_before.filled_quantity,
            order_remaining_quantity=context.order_before.remaining_quantity,
            economic_release_kind=(
                OnlyTerminalEconomicReleaseKind.MARGIN_RESERVATION
                if released_margin is not None
                else OnlyTerminalEconomicReleaseKind.CASH_RESERVATION
                if released_cash is not None
                else OnlyTerminalEconomicReleaseKind.POSITION_RESERVATION
            ),
            reservation_released_quantity=released_quantity,
            reservation_released_cash=released_cash,
            reservation_released_margin=released_margin,
            risk_released_quantity=risk_before.remaining_quantity,
            risk_released_notional=risk_before.remaining_notional,
            active_order_count_delta=-1,
            cluster_active_order_count_delta=-1,
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
            transaction_id=authority.terminal_identity,
            runtime_id=update.runtime_id,
            operation_kind=OnlyRuntimeOperationKind.ORDER_TERMINAL,
            operation_identity=authority.terminal_identity,
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
    def _validate(context: OnlyTerminalExecutionPlanningContext) -> None:
        order = context.order_before
        risk = context.risk_reservation_before
        if context.support_decision.capability is not OnlyExecutionCapability.DURABLE_TERMINAL:
            raise ValueError("Terminal capability routing invariant failed")
        if context.update.account_id != order.account_id or context.position_scope.cluster_id != order.cluster_id:
            raise ValueError("Terminal Account/Cluster scope disagrees")
        if risk.order_id != order.order_id or risk.remaining_quantity != order.remaining_quantity:
            raise ValueError("Risk Reservation remaining authority disagrees with Order")
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


def _events(
    context: OnlyTerminalExecutionPlanningContext,
    projections: tuple[OnlyRuntimeProjection, ...],
) -> tuple[OnlyEvent, ...]:
    factory = OnlyExecutionTransactionEventFactory()
    return tuple(
        factory.create(
            transaction_id=context.terminal_authority.terminal_identity,
            event_sequence=index,
            event_type=OnlyEventType(f"{projection.identity.component.value}_TERMINAL_APPLIED"),
            timestamp=context.update.ts_event.to_datetime(),
            engine_id=context.engine_id,
            runtime_id=context.update.runtime_id,
            cluster_id=context.order_before.cluster_id,
            source=OnlyEventSource("execution.terminal_planner"),
            payload={
                "terminal_identity": context.terminal_authority.terminal_identity,
                "terminal_status": context.terminal_authority.terminal_status.value,
                "component": projection.identity.component.value,
            },
            ts_init=context.update.ts_init.to_datetime(),
            metadata={"broker_update_id": str(context.update.update_id)},
        )
        for index, projection in enumerate(projections, start=1)
    )


__all__ = ["OnlyTerminalExecutionTransactionPlanner"]
