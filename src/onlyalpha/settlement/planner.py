"""Pure planner for Settlement Maturity Runtime transactions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from onlyalpha.account.models import OnlyAccountSnapshot
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyMoney, OnlyQuantity
from onlyalpha.execution.authority_state import only_settlement_execution_state
from onlyalpha.execution.execution_state import (
    only_account_execution_state,
    only_allocation_execution_state,
    only_position_execution_state,
)
from onlyalpha.position.models import OnlyPositionAllocationSnapshot, OnlyPositionSnapshot
from onlyalpha.settlement.facts import OnlySettlementMaturityFactDraft
from onlyalpha.settlement.identity import OnlySettlementMaturityIdentity
from onlyalpha.settlement.models import (
    OnlySettlementInstructionSnapshot,
    OnlySettlementInstructionStatus,
    OnlySettlementLegDirection,
    OnlySettlementTransitionKind,
)
from onlyalpha.transaction.enums import OnlyRuntimeOperationKind
from onlyalpha.transaction.projection import (
    OnlyAccountExecutionProjection,
    OnlyAllocationExecutionProjection,
    OnlyAllocationExecutionReplayMetadata,
    OnlyPositionExecutionProjection,
    OnlyPositionExecutionReplayMetadata,
    OnlyRuntimeProjection,
    OnlyRuntimeProjectionComponent,
    OnlySettlementExecutionProjection,
)
from onlyalpha.transaction.projection_builder import OnlyRuntimeProjectionBuilder
from onlyalpha.transaction.state_hash import only_execution_state_hash
from onlyalpha.transaction.transaction import OnlyPreparedRuntimeTransaction, OnlyRuntimePrecondition


@dataclass(frozen=True, slots=True)
class OnlySettlementMaturityPlanningContext:
    instruction_before: OnlySettlementInstructionSnapshot
    position_before: OnlyPositionSnapshot
    position_cycle: int
    allocation_before: OnlyPositionAllocationSnapshot
    allocation_cycle: int
    account_before: OnlyAccountSnapshot
    effective_on: OnlyTradingDay
    processed_at: OnlyTimestamp
    transitions: tuple[OnlySettlementTransitionKind, ...]


class OnlySettlementMaturityPlanner:
    def prepare(self, context: OnlySettlementMaturityPlanningContext) -> OnlyPreparedRuntimeTransaction:
        instruction = context.instruction_before.instruction
        transitions = tuple(sorted(set(context.transitions), key=lambda item: item.value))
        if not transitions or context.position_cycle != instruction.position_cycle:
            raise ValueError("SETTLEMENT_POSITION_LIFECYCLE_CONFLICT")
        if context.allocation_cycle != instruction.allocation_cycle:
            raise ValueError("SETTLEMENT_ALLOCATION_LIFECYCLE_CONFLICT")
        if context.position_before.position_id != instruction.position_id:
            raise ValueError("SETTLEMENT_POSITION_LIFECYCLE_CONFLICT")
        if context.allocation_before.allocation_id != instruction.allocation_id:
            raise ValueError("SETTLEMENT_ALLOCATION_LIFECYCLE_CONFLICT")
        before_fingerprint = only_execution_state_hash(context.instruction_before)
        identity_model = OnlySettlementMaturityIdentity(
            instruction.runtime_id,
            instruction.instruction_id,
            context.effective_on,
            transitions,
        )
        maturity_identity = identity_model.value(before_fingerprint)
        projections = self._projections(context, transitions, maturity_identity)
        asset_delta = (
            instruction.trade_quantity
            if OnlySettlementTransitionKind.ASSET_TRADE_AVAILABLE in transitions
            and instruction.asset_leg.direction is OnlySettlementLegDirection.CREDIT
            else OnlyQuantity(Decimal(0), instruction.trade_quantity.precision)
        )
        zero_money = OnlyMoney(Decimal(0), instruction.gross_notional.currency)
        cash_withdrawable_delta = (
            instruction.cash_leg.account_availability_amount
            if OnlySettlementTransitionKind.CASH_WITHDRAWABLE in transitions
            and instruction.cash_leg.direction is OnlySettlementLegDirection.CREDIT
            else zero_money
        )
        fact = OnlySettlementMaturityFactDraft(
            maturity_identity,
            instruction.runtime_id,
            instruction.account_id,
            instruction.cluster_id,
            instruction.instrument_id,
            instruction.instruction_id,
            instruction.order_id,
            instruction.trade_id,
            context.effective_on,
            context.processed_at,
            transitions,
            asset_delta,
            zero_money,
            cash_withdrawable_delta,
            instruction.position_id,
            instruction.allocation_id,
            context.instruction_before.version,
            context.instruction_before.version + 1,
            instruction.compiled_rule_fingerprint,
            instruction.reference_fingerprint,
        )
        preconditions = tuple(
            OnlyRuntimePrecondition(
                item.identity.component,
                item.identity.entity_key,
                item.identity.expected_version,
                item.identity.expected_state_hash,
            )
            for item in projections
        )
        return OnlyPreparedRuntimeTransaction(
            transaction_id=maturity_identity,
            runtime_id=instruction.runtime_id,
            operation_kind=OnlyRuntimeOperationKind.SETTLEMENT_MATURITY,
            operation_identity=maturity_identity,
            account_id=instruction.account_id,
            effective_time=context.processed_at,
            prepared_at=context.processed_at,
            fact_draft=fact,
            projections=projections,
            outbox_events=(),
            preconditions=preconditions,
        )

    @staticmethod
    def _projections(
        context: OnlySettlementMaturityPlanningContext,
        transitions: tuple[OnlySettlementTransitionKind, ...],
        maturity_identity: str,
    ) -> tuple[OnlyRuntimeProjection, ...]:
        instruction = context.instruction_before.instruction
        builder = OnlyRuntimeProjectionBuilder()
        projections: list[OnlyRuntimeProjection] = []
        asset_matures = (
            OnlySettlementTransitionKind.ASSET_TRADE_AVAILABLE in transitions
            and instruction.asset_leg.direction is OnlySettlementLegDirection.CREDIT
        )
        if asset_matures:
            quantity = instruction.trade_quantity
            if context.position_before.unsettled_quantity.value < quantity.value:
                raise ValueError("SETTLEMENT_POSITION_UNSETTLED_INSUFFICIENT")
            if context.allocation_before.unsettled_quantity.value < quantity.value:
                raise ValueError("SETTLEMENT_ALLOCATION_UNSETTLED_INSUFFICIENT")
            position_before = only_position_execution_state(context.position_before)
            position_after = replace(
                position_before,
                settled_quantity=position_before.settled_quantity + quantity,
                unsettled_quantity=OnlyQuantity(
                    position_before.unsettled_quantity.value - quantity.value, quantity.precision
                ),
                updated_at=context.processed_at,
                version=position_before.version + 1,
            )
            allocation_before = only_allocation_execution_state(context.allocation_before)
            allocation_after = replace(
                allocation_before,
                settled_quantity=allocation_before.settled_quantity + quantity,
                unsettled_quantity=OnlyQuantity(
                    allocation_before.unsettled_quantity.value - quantity.value, quantity.precision
                ),
                updated_at=context.processed_at,
                version=allocation_before.version + 1,
            )
            position_identity = builder.identity(
                component=OnlyRuntimeProjectionComponent.POSITION,
                entity_key=str(position_after.position_id),
                before=position_before,
                after=position_after,
                projection_sequence=len(projections) + 1,
            )
            projections.append(
                builder.finalize(
                    OnlyPositionExecutionProjection(
                        position_identity,
                        position_before,
                        position_after,
                        OnlyMoney(Decimal(0), position_after.realized_pnl.currency),
                        OnlyPositionExecutionReplayMetadata(context.position_cycle),
                    )
                )
            )
            allocation_identity = builder.identity(
                component=OnlyRuntimeProjectionComponent.ALLOCATION,
                entity_key=str(allocation_after.allocation_id),
                before=allocation_before,
                after=allocation_after,
                projection_sequence=len(projections) + 1,
            )
            projections.append(
                builder.finalize(
                    OnlyAllocationExecutionProjection(
                        allocation_identity,
                        allocation_before,
                        allocation_after,
                        OnlyMoney(Decimal(0), allocation_after.realized_pnl.currency),
                        OnlyAllocationExecutionReplayMetadata(context.allocation_cycle),
                    )
                )
            )
        settlement_before = only_settlement_execution_state(context.instruction_before)
        asset_trade_available = (
            context.instruction_before.asset_trade_available
            or OnlySettlementTransitionKind.ASSET_TRADE_AVAILABLE in transitions
        )
        cash_trade_available = (
            context.instruction_before.cash_trade_available
            or OnlySettlementTransitionKind.CASH_TRADE_AVAILABLE in transitions
        )
        cash_withdrawable = (
            context.instruction_before.cash_withdrawable
            or OnlySettlementTransitionKind.CASH_WITHDRAWABLE in transitions
        )
        legal_settled = (
            context.instruction_before.legal_settled or OnlySettlementTransitionKind.LEGAL_SETTLED in transitions
        )
        complete = asset_trade_available and cash_trade_available and cash_withdrawable and legal_settled
        settlement_snapshot = replace(
            context.instruction_before,
            asset_trade_available=asset_trade_available,
            cash_trade_available=cash_trade_available,
            cash_withdrawable=cash_withdrawable,
            legal_settled=legal_settled,
            status=OnlySettlementInstructionStatus.COMPLETED
            if complete
            else OnlySettlementInstructionStatus.PARTIALLY_EFFECTIVE,
            version=context.instruction_before.version + 1,
            last_maturity_identity=maturity_identity,
        )
        settlement_after = replace(
            only_settlement_execution_state(settlement_snapshot),
            record_sequence_head=settlement_before.record_sequence_head + 1,
        )
        settlement_identity = builder.identity(
            component=OnlyRuntimeProjectionComponent.SETTLEMENT,
            entity_key=settlement_after.instruction_id,
            before=settlement_before,
            after=settlement_after,
            projection_sequence=len(projections) + 1,
        )
        projections.append(
            builder.finalize(
                OnlySettlementExecutionProjection(
                    settlement_identity,
                    settlement_before,
                    settlement_after,
                    (),
                )
            )
        )
        cash_matures = (
            OnlySettlementTransitionKind.CASH_WITHDRAWABLE in transitions
            and instruction.cash_leg.direction is OnlySettlementLegDirection.CREDIT
        )
        if cash_matures:
            amount = instruction.cash_leg.account_availability_amount
            if context.account_before.cash.unsettled_receivable_cash.amount < amount.amount:
                raise ValueError("SETTLEMENT_ACCOUNT_RECEIVABLE_INSUFFICIENT")
            account_before = only_account_execution_state(context.account_before)
            unsettled = OnlyMoney(account_before.unsettled_receivable_cash.amount - amount.amount, amount.currency)
            account_after = replace(
                account_before,
                unsettled_receivable_cash=unsettled,
                withdrawable_cash=OnlyMoney(
                    account_before.trade_available_cash.amount - unsettled.amount, amount.currency
                ),
                updated_at=context.processed_at,
                version=account_before.version + 1,
            )
            account_identity = builder.identity(
                component=OnlyRuntimeProjectionComponent.ACCOUNT,
                entity_key=str(account_after.account_id),
                before=account_before,
                after=account_after,
                projection_sequence=len(projections) + 1,
            )
            projections.append(
                builder.finalize(OnlyAccountExecutionProjection(account_identity, account_before, account_after))
            )
        return tuple(projections)


__all__ = ["OnlySettlementMaturityPlanner", "OnlySettlementMaturityPlanningContext"]
