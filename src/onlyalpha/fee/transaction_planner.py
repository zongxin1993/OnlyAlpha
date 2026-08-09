"""Pure planner for durable FEE_RECONCILIATION Runtime transactions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.execution.execution_state import (
    OnlyAccountExecutionState,
    OnlyStrategyLedgerExecutionState,
)
from onlyalpha.fee.adjustment import (
    OnlyFeeAdjustmentDirection,
    OnlyUnallocatedExternalFeeState,
)
from onlyalpha.fee.evidence import OnlyExternalFeeEvidence
from onlyalpha.fee.facts import OnlyFeeReconciliationFactDraft
from onlyalpha.fee.reconciliation import OnlyFeeReconciliationDecision, OnlyFeeReconciliationStatus
from onlyalpha.fee.reconciliation_authority import (
    OnlyExternalFeeEvidenceState,
    OnlyFeeAdjustmentState,
    OnlyFeeReconciliationDecisionState,
)
from onlyalpha.fee.risk_gate import (
    OnlyFeeReconciliationBlocker,
    OnlyFeeReconciliationRiskGateState,
)
from onlyalpha.transaction.enums import OnlyRuntimeOperationKind
from onlyalpha.transaction.projection import (
    OnlyAccountExecutionProjection,
    OnlyExternalFeeEvidenceProjection,
    OnlyFeeAdjustmentProjection,
    OnlyFeeReconciliationProjection,
    OnlyFeeReconciliationRiskGateProjection,
    OnlyRuntimeProjection,
    OnlyRuntimeProjectionComponent,
    OnlyStrategyLedgerExecutionProjection,
    OnlyUnallocatedExternalFeeProjection,
)
from onlyalpha.transaction.projection_builder import OnlyRuntimeProjectionBuilder
from onlyalpha.transaction.transaction import OnlyPreparedRuntimeTransaction, OnlyRuntimePrecondition


@dataclass(frozen=True, slots=True)
class OnlyFeeReconciliationPlanningContext:
    runtime_id: OnlyRuntimeId
    evidence: OnlyExternalFeeEvidence
    decision: OnlyFeeReconciliationDecision
    processed_at: OnlyTimestamp
    evidence_before: OnlyExternalFeeEvidenceState | None
    decision_before: OnlyFeeReconciliationDecisionState | None
    adjustment_before: tuple[OnlyFeeAdjustmentState | None, ...]
    account_before: OnlyAccountExecutionState | None
    strategy_ledger_before: OnlyStrategyLedgerExecutionState | None
    unallocated_before: OnlyUnallocatedExternalFeeState | None
    risk_gate_before: OnlyFeeReconciliationRiskGateState | None


class OnlyFeeReconciliationTransactionPlanner:
    def prepare(self, context: OnlyFeeReconciliationPlanningContext) -> OnlyPreparedRuntimeTransaction:
        if any(context.evidence.account_id != adjustment.account_id for adjustment in context.decision.adjustments):
            raise ValueError("FEE_RECONCILIATION_ACCOUNT_SCOPE_CONFLICT")
        if len(context.adjustment_before) != len(context.decision.adjustments):
            raise ValueError("FEE_RECONCILIATION_ADJUSTMENT_AUTHORITY_MISSING")
        builder = OnlyRuntimeProjectionBuilder()
        projections: list[OnlyRuntimeProjection] = []

        evidence_after = OnlyExternalFeeEvidenceState(
            context.evidence,
            context.decision.status is not OnlyFeeReconciliationStatus.EVIDENCE_CONFLICT,
            1 if context.evidence_before is None else context.evidence_before.version + 1,
        )
        identity = builder.identity(
            component=OnlyRuntimeProjectionComponent.EXTERNAL_FEE_EVIDENCE,
            entity_key=context.evidence.evidence_id,
            before=context.evidence_before,
            after=evidence_after,
            projection_sequence=len(projections) + 1,
        )
        projections.append(
            builder.finalize(OnlyExternalFeeEvidenceProjection(identity, context.evidence_before, evidence_after))
        )
        decision_after = OnlyFeeReconciliationDecisionState(
            context.decision,
            1 if context.decision_before is None else context.decision_before.version + 1,
        )
        identity = builder.identity(
            component=OnlyRuntimeProjectionComponent.FEE_RECONCILIATION,
            entity_key=context.decision.reconciliation_id,
            before=context.decision_before,
            after=decision_after,
            projection_sequence=len(projections) + 1,
        )
        projections.append(
            builder.finalize(OnlyFeeReconciliationProjection(identity, context.decision_before, decision_after))
        )

        signed_total = Decimal(0)
        total_charges = Decimal(0)
        total_refunds = Decimal(0)
        for adjustment, adjustment_before in zip(
            context.decision.adjustments,
            context.adjustment_before,
            strict=True,
        ):
            adjustment_after = OnlyFeeAdjustmentState(
                adjustment,
                1 if adjustment_before is None else adjustment_before.version + 1,
            )
            identity = builder.identity(
                component=OnlyRuntimeProjectionComponent.FEE_ADJUSTMENT_LEDGER,
                entity_key=adjustment.adjustment_id,
                before=adjustment_before,
                after=adjustment_after,
                projection_sequence=len(projections) + 1,
            )
            projections.append(
                builder.finalize(OnlyFeeAdjustmentProjection(identity, adjustment_before, adjustment_after))
            )
            signed = (
                adjustment.amount.amount
                if adjustment.direction is OnlyFeeAdjustmentDirection.SUPPLEMENTAL_CHARGE
                else -adjustment.amount.amount
            )
            signed_total += signed
            total_charges += adjustment.amount.amount if signed > 0 else Decimal(0)
            total_refunds += adjustment.amount.amount if signed < 0 else Decimal(0)

        adjustments = context.decision.adjustments
        if adjustments:
            if context.account_before is None:
                raise ValueError("FEE_RECONCILIATION_ACCOUNT_AUTHORITY_MISSING")
            currency = adjustments[0].amount.currency
            if any(item.amount.currency != currency for item in adjustments):
                raise ValueError("FEE_EVIDENCE_CURRENCY_CONFLICT")
            account_after = self._adjust_account(
                context.account_before,
                signed_total,
                OnlyMoney(abs(signed_total), currency),
                context.processed_at,
            )
            identity = builder.identity(
                component=OnlyRuntimeProjectionComponent.ACCOUNT,
                entity_key=str(account_after.account_id),
                before=context.account_before,
                after=account_after,
                projection_sequence=len(projections) + 1,
            )
            projections.append(
                builder.finalize(OnlyAccountExecutionProjection(identity, context.account_before, account_after))
            )
            cluster_ids = {item.cluster_id for item in adjustments}
            if len(cluster_ids) != 1:
                raise ValueError("FEE_RECONCILIATION_STRATEGY_AUTHORITY_MISSING")
            cluster_id = next(iter(cluster_ids))
            if cluster_id is not None:
                if context.strategy_ledger_before is None:
                    raise ValueError("FEE_RECONCILIATION_STRATEGY_AUTHORITY_MISSING")
                ledger_after = self._adjust_strategy(
                    context.strategy_ledger_before,
                    signed_total,
                    OnlyMoney(abs(signed_total), currency),
                    context.processed_at,
                )
                identity = builder.identity(
                    component=OnlyRuntimeProjectionComponent.STRATEGY_LEDGER,
                    entity_key=str(ledger_after.ledger_id),
                    before=context.strategy_ledger_before,
                    after=ledger_after,
                    projection_sequence=len(projections) + 1,
                )
                projections.append(
                    builder.finalize(
                        OnlyStrategyLedgerExecutionProjection(identity, context.strategy_ledger_before, ledger_after)
                    )
                )
            else:
                zero = OnlyMoney(Decimal(0), currency)
                before = context.unallocated_before
                charges = zero if before is None else before.cumulative_charges
                refunds = zero if before is None else before.cumulative_refunds
                unallocated_after = OnlyUnallocatedExternalFeeState(
                    context.evidence.account_id,
                    charges + OnlyMoney(total_charges, currency),
                    refunds + OnlyMoney(total_refunds, currency),
                    1 if before is None else before.version + 1,
                )
                identity = builder.identity(
                    component=OnlyRuntimeProjectionComponent.UNALLOCATED_EXTERNAL_FEE,
                    entity_key=str(context.evidence.account_id),
                    before=before,
                    after=unallocated_after,
                    projection_sequence=len(projections) + 1,
                )
                projections.append(
                    builder.finalize(OnlyUnallocatedExternalFeeProjection(identity, before, unallocated_after))
                )

        gate_before = context.risk_gate_before
        blockers = list(() if gate_before is None else gate_before.active_blockers)
        if context.decision.resolves_blocker_id is not None:
            blockers = [item for item in blockers if item.blocker_id != context.decision.resolves_blocker_id]
        if context.decision.status is OnlyFeeReconciliationStatus.TRADING_BLOCKED:
            blockers = [
                item
                for item in blockers
                if item.evidence_family_fingerprint != context.decision.evidence_family_fingerprint
            ]
            if context.decision.reason is None:
                raise ValueError("FEE_RECONCILIATION_BLOCKER_CONFLICT")
            blockers.append(
                OnlyFeeReconciliationBlocker.create(
                    account_id=context.evidence.account_id,
                    evidence_family_fingerprint=context.decision.evidence_family_fingerprint,
                    evidence_id=context.evidence.evidence_id,
                    reconciliation_id=context.decision.reconciliation_id,
                    reason=context.decision.reason,
                    scope=context.evidence.scope,
                    policy_identity=context.decision.policy_identity,
                    created_at=context.processed_at,
                )
            )
        gate_after = OnlyFeeReconciliationRiskGateState(
            context.evidence.account_id,
            tuple(sorted(blockers, key=lambda item: item.blocker_id)),
            1 if gate_before is None else gate_before.version + 1,
        )
        identity = builder.identity(
            component=OnlyRuntimeProjectionComponent.RECONCILIATION_RISK_GATE,
            entity_key=str(context.evidence.account_id),
            before=gate_before,
            after=gate_after,
            projection_sequence=len(projections) + 1,
        )
        projections.append(builder.finalize(OnlyFeeReconciliationRiskGateProjection(identity, gate_before, gate_after)))
        fact = OnlyFeeReconciliationFactDraft(
            context.runtime_id,
            context.evidence.account_id,
            context.evidence,
            context.decision,
            context.processed_at,
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
            transaction_id=context.decision.reconciliation_id,
            runtime_id=context.runtime_id,
            operation_kind=OnlyRuntimeOperationKind.FEE_RECONCILIATION,
            operation_identity=context.decision.reconciliation_id,
            account_id=context.evidence.account_id,
            effective_time=context.evidence.effective_at,
            prepared_at=context.processed_at,
            fact_draft=fact,
            projections=tuple(projections),
            outbox_events=(),
            preconditions=preconditions,
        )

    @staticmethod
    def _adjust_account(
        before: OnlyAccountExecutionState, signed: Decimal, amount: OnlyMoney, timestamp: OnlyTimestamp
    ) -> OnlyAccountExecutionState:
        delta = amount.amount if signed > 0 else -amount.amount
        cash = OnlyMoney(before.ledger_cash.amount - delta, amount.currency)
        if cash.amount < 0:
            raise ValueError("FEE_RECONCILIATION_ACCOUNT_CASH_INSUFFICIENT")
        trade = OnlyMoney(cash.amount - before.order_reserved_cash.amount, amount.currency)
        withdrawable = OnlyMoney(trade.amount - before.unsettled_receivable_cash.amount, amount.currency)
        return replace(
            before,
            ledger_cash=cash,
            trade_available_cash=trade,
            withdrawable_cash=withdrawable,
            fees=OnlyMoney(before.fees.amount + delta, amount.currency),
            equity=OnlyMoney(cash.amount + before.position_market_value.amount, amount.currency),
            updated_at=timestamp,
            version=before.version + 1,
        )

    @staticmethod
    def _adjust_strategy(
        before: OnlyStrategyLedgerExecutionState, signed: Decimal, amount: OnlyMoney, timestamp: OnlyTimestamp
    ) -> OnlyStrategyLedgerExecutionState:
        delta = amount.amount if signed > 0 else -amount.amount
        cash = OnlyMoney(before.ledger_cash.amount - delta, amount.currency)
        available = OnlyMoney(cash.amount - before.cash_reserved.amount, amount.currency)
        return replace(
            before,
            ledger_cash=cash,
            cash_available=available,
            fees=OnlyMoney(before.fees.amount + delta, amount.currency),
            equity=OnlyMoney(cash.amount + before.position_market_value.amount, amount.currency),
            updated_at=timestamp,
            valuation_time=timestamp,
            version=before.version + 1,
        )


__all__ = ["OnlyFeeReconciliationPlanningContext", "OnlyFeeReconciliationTransactionPlanner"]
