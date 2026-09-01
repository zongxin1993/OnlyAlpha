"""Pure planner for the canonical durable local Order Intent boundary."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.execution.execution_state import (
    OnlyAccountCashReservationExecutionState,
    OnlyAccountExecutionState,
    OnlyAllocationExecutionState,
    OnlyMarginReservationExecutionState,
    OnlyOrderExecutionState,
    OnlyPositionExecutionState,
    OnlyPositionReservationExecutionState,
    OnlyRiskExecutionState,
    OnlyRiskReservationExecutionState,
    OnlyStrategyCashReservationExecutionState,
    OnlyStrategyLedgerExecutionState,
)
from onlyalpha.transaction.enums import OnlyRuntimeOperationKind
from onlyalpha.transaction.projection import (
    OnlyAccountCashReservationExecutionProjection,
    OnlyAccountExecutionProjection,
    OnlyAllocationExecutionProjection,
    OnlyAllocationExecutionReplayMetadata,
    OnlyMarginReservationExecutionProjection,
    OnlyOrderIntentExecutionProjection,
    OnlyPositionExecutionProjection,
    OnlyPositionExecutionReplayMetadata,
    OnlyPositionReservationExecutionProjection,
    OnlyRiskExecutionProjection,
    OnlyRiskReservationExecutionProjection,
    OnlyRuntimeProjection,
    OnlyRuntimeProjectionComponent,
    OnlyRuntimeProjectionOrder,
    OnlyStrategyCashReservationExecutionProjection,
    OnlyStrategyLedgerExecutionProjection,
)
from onlyalpha.transaction.projection_builder import OnlyRuntimeProjectionBuilder
from onlyalpha.transaction.transaction import OnlyPreparedRuntimeTransaction, OnlyRuntimePrecondition

from .order_intent_fact import OnlyOrderIntentFactDraft
from .reference import OnlyExecutionReferenceEvidence

ONLY_ORDER_INTENT_IDENTITY_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class OnlyOrderIntentPositionChange:
    before: OnlyPositionExecutionState
    after: OnlyPositionExecutionState
    cycle: int


@dataclass(frozen=True, slots=True)
class OnlyOrderIntentAllocationChange:
    before: OnlyAllocationExecutionState
    after: OnlyAllocationExecutionState
    cycle: int


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyOrderIntentPlanningContext:
    order_after: OnlyOrderExecutionState
    prepared_at: OnlyTimestamp
    account_before: OnlyAccountExecutionState
    account_after: OnlyAccountExecutionState
    strategy_ledger_before: OnlyStrategyLedgerExecutionState
    strategy_ledger_after: OnlyStrategyLedgerExecutionState
    position_changes: tuple[OnlyOrderIntentPositionChange, ...] = ()
    allocation_changes: tuple[OnlyOrderIntentAllocationChange, ...] = ()
    account_cash_reservation_after: OnlyAccountCashReservationExecutionState | None = None
    strategy_cash_reservation_after: OnlyStrategyCashReservationExecutionState | None = None
    position_reservation_after: OnlyPositionReservationExecutionState | None = None
    margin_reservation_after: OnlyMarginReservationExecutionState | None = None
    risk_reservation_after: OnlyRiskReservationExecutionState | None = None
    risk_before: OnlyRiskExecutionState | None = None
    risk_after: OnlyRiskExecutionState | None = None
    execution_reference: OnlyExecutionReferenceEvidence | None = None


@dataclass(frozen=True, slots=True)
class _OnlyOrderIntentProjectionSpec:
    component: OnlyRuntimeProjectionComponent
    before: OnlyDomainModel | None
    after: OnlyDomainModel
    entity_key: str
    replay_cycle: int | None = None


class OnlyOrderIntentRuntimeTransactionPlanner:
    def prepare(self, context: OnlyOrderIntentPlanningContext) -> OnlyPreparedRuntimeTransaction:
        order = context.order_after
        prepared_at = context.prepared_at
        if prepared_at < order.created_at:
            raise ValueError("ORDER_INTENT_PREPARED_TIME_INVALID")
        if context.margin_reservation_after is not None:
            raise ValueError("ORDER_INTENT_MARGIN_RESERVATION_PROJECTION_UNSUPPORTED")
        identity_payload = "\x1f".join(
            (
                str(ONLY_ORDER_INTENT_IDENTITY_SCHEMA_VERSION),
                str(order.runtime_id),
                str(order.account_id),
                str(order.cluster_id),
                str(order.request_id),
            )
        )
        intent_identity = f"OINT-{hashlib.sha256(identity_payload.encode('utf-8')).hexdigest()}"
        builder = OnlyRuntimeProjectionBuilder()
        specs = [
            _OnlyOrderIntentProjectionSpec(
                OnlyRuntimeProjectionComponent.ORDER,
                None,
                order,
                str(order.order_id),
            )
        ]
        specs.extend(
            _OnlyOrderIntentProjectionSpec(
                OnlyRuntimeProjectionComponent.POSITION,
                change.before,
                change.after,
                str(change.after.position_id),
                change.cycle,
            )
            for change in context.position_changes
        )
        specs.extend(
            _OnlyOrderIntentProjectionSpec(
                OnlyRuntimeProjectionComponent.ALLOCATION,
                change.before,
                change.after,
                str(change.after.allocation_id),
                change.cycle,
            )
            for change in context.allocation_changes
        )
        if context.account_before != context.account_after:
            specs.append(
                _OnlyOrderIntentProjectionSpec(
                    OnlyRuntimeProjectionComponent.ACCOUNT,
                    context.account_before,
                    context.account_after,
                    str(order.account_id),
                )
            )
        if context.strategy_ledger_before != context.strategy_ledger_after:
            specs.append(
                _OnlyOrderIntentProjectionSpec(
                    OnlyRuntimeProjectionComponent.STRATEGY_LEDGER,
                    context.strategy_ledger_before,
                    context.strategy_ledger_after,
                    str(context.strategy_ledger_after.ledger_id),
                )
            )
        for component, state in (
            (OnlyRuntimeProjectionComponent.ACCOUNT_CASH_RESERVATION, context.account_cash_reservation_after),
            (OnlyRuntimeProjectionComponent.STRATEGY_CASH_RESERVATION, context.strategy_cash_reservation_after),
            (OnlyRuntimeProjectionComponent.POSITION_RESERVATION, context.position_reservation_after),
            (OnlyRuntimeProjectionComponent.MARGIN_RESERVATION, context.margin_reservation_after),
            (OnlyRuntimeProjectionComponent.RISK_RESERVATION, context.risk_reservation_after),
        ):
            if state is not None:
                specs.append(_OnlyOrderIntentProjectionSpec(component, None, state, str(state.reservation_id)))
        if (
            context.risk_before is not None
            and context.risk_after is not None
            and context.risk_before != context.risk_after
        ):
            specs.append(
                _OnlyOrderIntentProjectionSpec(
                    OnlyRuntimeProjectionComponent.RISK,
                    context.risk_before,
                    context.risk_after,
                    str(order.cluster_id),
                )
            )
        specs.sort(key=lambda item: (OnlyRuntimeProjectionOrder[item.component.name], item.entity_key))
        projections: list[OnlyRuntimeProjection] = []
        for sequence, spec in enumerate(specs, 1):
            component = spec.component
            before = spec.before
            after = spec.after
            projection_identity = builder.identity(
                component=component,
                entity_key=spec.entity_key,
                before=before,
                after=after,
                projection_sequence=sequence,
            )
            projection: OnlyRuntimeProjection
            if component is OnlyRuntimeProjectionComponent.ORDER:
                projection = OnlyOrderIntentExecutionProjection(projection_identity, None, order)
            elif component is OnlyRuntimeProjectionComponent.POSITION:
                assert isinstance(before, OnlyPositionExecutionState)
                assert isinstance(after, OnlyPositionExecutionState)
                assert spec.replay_cycle is not None
                projection = OnlyPositionExecutionProjection(
                    projection_identity,
                    before,
                    after,
                    OnlyMoney(Decimal(0), after.realized_pnl.currency),
                    OnlyPositionExecutionReplayMetadata(spec.replay_cycle),
                )
            elif component is OnlyRuntimeProjectionComponent.ALLOCATION:
                assert isinstance(before, OnlyAllocationExecutionState)
                assert isinstance(after, OnlyAllocationExecutionState)
                assert spec.replay_cycle is not None
                projection = OnlyAllocationExecutionProjection(
                    projection_identity,
                    before,
                    after,
                    OnlyMoney(Decimal(0), after.realized_pnl.currency),
                    OnlyAllocationExecutionReplayMetadata(spec.replay_cycle),
                )
            elif component is OnlyRuntimeProjectionComponent.ACCOUNT:
                assert isinstance(before, OnlyAccountExecutionState)
                assert isinstance(after, OnlyAccountExecutionState)
                projection = OnlyAccountExecutionProjection(projection_identity, before, after)
            elif component is OnlyRuntimeProjectionComponent.STRATEGY_LEDGER:
                assert isinstance(before, OnlyStrategyLedgerExecutionState)
                assert isinstance(after, OnlyStrategyLedgerExecutionState)
                projection = OnlyStrategyLedgerExecutionProjection(projection_identity, before, after)
            elif component is OnlyRuntimeProjectionComponent.ACCOUNT_CASH_RESERVATION:
                assert isinstance(after, OnlyAccountCashReservationExecutionState)
                projection = OnlyAccountCashReservationExecutionProjection(projection_identity, None, after)
            elif component is OnlyRuntimeProjectionComponent.STRATEGY_CASH_RESERVATION:
                assert isinstance(after, OnlyStrategyCashReservationExecutionState)
                projection = OnlyStrategyCashReservationExecutionProjection(projection_identity, None, after)
            elif component is OnlyRuntimeProjectionComponent.POSITION_RESERVATION:
                assert isinstance(after, OnlyPositionReservationExecutionState)
                projection = OnlyPositionReservationExecutionProjection(projection_identity, None, after)
            elif component is OnlyRuntimeProjectionComponent.MARGIN_RESERVATION:
                assert isinstance(after, OnlyMarginReservationExecutionState)
                projection = OnlyMarginReservationExecutionProjection(projection_identity, None, after)
            elif component is OnlyRuntimeProjectionComponent.RISK_RESERVATION:
                assert isinstance(after, OnlyRiskReservationExecutionState)
                projection = OnlyRiskReservationExecutionProjection(projection_identity, None, after)
            else:
                assert isinstance(before, OnlyRiskExecutionState)
                assert isinstance(after, OnlyRiskExecutionState)
                projection = OnlyRiskExecutionProjection(projection_identity, before, after)
            projections.append(builder.finalize(projection))
        reservation_ids = tuple(
            sorted(
                str(item.reservation_id)
                for item in (
                    context.account_cash_reservation_after,
                    context.strategy_cash_reservation_after,
                    context.position_reservation_after,
                    context.margin_reservation_after,
                    context.risk_reservation_after,
                )
                if item is not None
            )
        )
        fact = OnlyOrderIntentFactDraft(
            operation_kind=OnlyRuntimeOperationKind.ORDER_INTENT,
            intent_identity=intent_identity,
            runtime_id=order.runtime_id,
            account_id=order.account_id,
            cluster_id=order.cluster_id,
            order_id=order.order_id,
            order=order,
            reservation_identities=reservation_ids,
            causal_reference=str(order.request_id),
            ts_event=order.created_at,
            prepared_at=prepared_at,
            execution_reference=context.execution_reference,
        )
        return OnlyPreparedRuntimeTransaction(
            transaction_id=intent_identity,
            runtime_id=order.runtime_id,
            operation_kind=OnlyRuntimeOperationKind.ORDER_INTENT,
            operation_identity=intent_identity,
            account_id=order.account_id,
            effective_time=order.created_at,
            prepared_at=prepared_at,
            fact_draft=fact,
            projections=tuple(projections),
            outbox_events=(),
            preconditions=tuple(
                OnlyRuntimePrecondition(
                    item.identity.component,
                    item.identity.entity_key,
                    item.identity.expected_version,
                    item.identity.expected_state_hash,
                )
                for item in projections
            ),
        )


__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("ONLY_")]
