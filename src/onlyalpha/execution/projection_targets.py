"""Real Manager targets for committed Generic T0 cash projections."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum

from onlyalpha.account.identifiers import OnlyAccountReservationId
from onlyalpha.account.manager import OnlyAccountManager
from onlyalpha.account.models import OnlyAccountCashBalance, OnlyAccountReservation, OnlyAccountSnapshot
from onlyalpha.account.performance import OnlyAccountPerformanceProjector
from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.identifiers import OnlyAccountId
from onlyalpha.domain.value import OnlyMoney, OnlyRate
from onlyalpha.fee.accrual_manager import OnlyOrderFeeAccrualManager
from onlyalpha.fee.ledger import OnlyFeeApplicationLedger
from onlyalpha.fee.reconciliation_authority import OnlyFeeReconciliationAuthority
from onlyalpha.fee.risk_gate import OnlyFeeReconciliationRiskGate
from onlyalpha.order.manager import OnlyOrderManager
from onlyalpha.position.allocation_manager import OnlyPositionAllocationManager
from onlyalpha.position.manager import OnlyPositionManager
from onlyalpha.position.models import OnlyPositionAllocationSnapshot, OnlyPositionSnapshot
from onlyalpha.position.reservations import OnlyPositionReservation, OnlyPositionReservationManager
from onlyalpha.risk.reservations import OnlyRiskReservation
from onlyalpha.risk.service import OnlyRiskService
from onlyalpha.risk.snapshots import OnlyRiskSnapshot
from onlyalpha.settlement.authority import OnlySettlementAuthority
from onlyalpha.settlement.facts import OnlyCommittedSettlementMaturityFact
from onlyalpha.settlement.models import OnlySettlementInstructionSnapshot, OnlySettlementInstructionStatus
from onlyalpha.strategy_ledger.manager import OnlyStrategyLedgerManager
from onlyalpha.strategy_ledger.models import (
    OnlyStrategyCashReservation,
    OnlyStrategyCashSnapshot,
    OnlyStrategyLedgerSnapshot,
    OnlyStrategyPnLSnapshot,
)
from onlyalpha.transaction.applied_projection import (
    OnlyAppliedRuntimeProjectionLedger,
    OnlyAppliedRuntimeProjectionRecord,
    OnlyRuntimeProjectionApplyContext,
)
from onlyalpha.transaction.projection import (
    OnlyAccountCashReservationExecutionProjection,
    OnlyAccountExecutionProjection,
    OnlyAllocationExecutionProjection,
    OnlyExternalFeeEvidenceProjection,
    OnlyFeeAdjustmentProjection,
    OnlyFeeApplicationProjection,
    OnlyFeeReconciliationProjection,
    OnlyFeeReconciliationRiskGateProjection,
    OnlyOrderAcceptedExecutionProjection,
    OnlyOrderExecutionProjection,
    OnlyOrderFeeAccrualProjection,
    OnlyOrderTerminalExecutionProjection,
    OnlyPositionExecutionProjection,
    OnlyPositionReservationExecutionProjection,
    OnlyProjectionApplyResult,
    OnlyProjectionApplyStatus,
    OnlyRiskExecutionProjection,
    OnlyRiskReservationExecutionProjection,
    OnlyRuntimeProjectionComponent,
    OnlyRuntimeProjectionTarget,
    OnlySettlementExecutionProjection,
    OnlyStrategyCashReservationExecutionProjection,
    OnlyStrategyLedgerExecutionProjection,
    OnlyUnallocatedExternalFeeProjection,
    OnlyValuationExecutionProjection,
    OnlyValuationExecutionState,
)
from onlyalpha.transaction.state_hash import only_execution_state_hash

from .accepted_fact import OnlyCommittedOrderAcceptedFact
from .authority_state import (
    only_fee_application_state,
    only_settlement_execution_state,
)
from .committed import OnlyCommittedExecutionFact
from .execution_state import (
    OnlyAccountExecutionState,
    OnlyAllocationExecutionState,
    OnlyOrderExecutionState,
    OnlyPositionExecutionState,
    OnlyPositionReservationExecutionState,
    OnlyStrategyLedgerExecutionState,
    only_account_cash_reservation_execution_state,
    only_account_execution_state,
    only_allocation_execution_state,
    only_order_execution_state,
    only_position_execution_state,
    only_position_reservation_execution_state,
    only_risk_execution_state,
    only_risk_reservation_execution_state,
    only_strategy_cash_reservation_execution_state,
    only_strategy_ledger_execution_state,
)
from .terminal_fact import OnlyCommittedTerminalExecutionFact


def only_execution_trade_fingerprints(context: OnlyRuntimeProjectionApplyContext) -> tuple[str, ...]:
    fact = context.fact
    if not isinstance(fact, OnlyCommittedExecutionFact):
        return ()
    values = {f"trade:{fact.trade_id}", f"execution:{fact.broker_update_id}"}
    if fact.venue_trade_id is not None:
        values.add(f"venue:{fact.venue_trade_id}")
    return tuple(sorted(values))


def _version(state: OnlyDomainModel | None) -> int:
    if state is None:
        return 0
    value = state.to_dict().get("version")
    if not isinstance(value, int):
        raise TypeError("Projection state does not expose an integer version")
    return value


class _OnlyProjectionApplyDecision(StrEnum):
    APPLY = "APPLY"
    RECOVER = "RECOVER"


@dataclass(frozen=True, slots=True)
class _OnlyProjectionApplyPreparation:
    decision: _OnlyProjectionApplyDecision
    record: OnlyAppliedRuntimeProjectionRecord


class _OnlyProjectionTargetBase:
    def __init__(
        self,
        component: OnlyRuntimeProjectionComponent,
        applied_ledger: OnlyAppliedRuntimeProjectionLedger,
    ) -> None:
        self._component = component
        self._applied_ledger = applied_ledger

    @property
    def component(self) -> OnlyRuntimeProjectionComponent:
        return self._component

    def _prepare(
        self,
        context: OnlyRuntimeProjectionApplyContext,
        current: OnlyDomainModel | None,
    ) -> OnlyProjectionApplyResult | _OnlyProjectionApplyPreparation:
        identity = context.projection.identity
        if identity.component is not self.component:
            return self._result(OnlyProjectionApplyStatus.INVALID_COMPONENT, context, current)
        prior = self._applied_ledger.get(context.execution_sequence, self.component)
        record = OnlyAppliedRuntimeProjectionRecord(
            context.transaction_id,
            context.execution_sequence,
            self.component,
            identity.entity_key,
            identity.payload_hash,
            identity.result_state_hash,
        )
        if prior is not None:
            status = (
                OnlyProjectionApplyStatus.IDEMPOTENT if prior == record else OnlyProjectionApplyStatus.PAYLOAD_CONFLICT
            )
            return self._result(status, context, current)
        if only_execution_state_hash(context.projection.after) != identity.result_state_hash:
            return self._result(OnlyProjectionApplyStatus.STATE_CONFLICT, context, current)
        current_version = _version(current)
        current_hash = only_execution_state_hash(current)
        if current_version == identity.expected_version and current_hash == identity.expected_state_hash:
            return _OnlyProjectionApplyPreparation(_OnlyProjectionApplyDecision.APPLY, record)
        if current_version == identity.result_version and current_hash == identity.result_state_hash:
            return _OnlyProjectionApplyPreparation(_OnlyProjectionApplyDecision.RECOVER, record)
        if current_version not in {identity.expected_version, identity.result_version}:
            return self._result(OnlyProjectionApplyStatus.VERSION_CONFLICT, context, current)
        return self._result(OnlyProjectionApplyStatus.STATE_CONFLICT, context, current)

    def _complete(
        self,
        context: OnlyRuntimeProjectionApplyContext,
        before: OnlyDomainModel | None,
        after: OnlyDomainModel,
        preparation: _OnlyProjectionApplyPreparation,
    ) -> OnlyProjectionApplyResult:
        if only_execution_state_hash(after) != context.projection.identity.result_state_hash:
            raise RuntimeError(f"{self.component.value} Projection installation produced the wrong authority")
        self._applied_ledger.record(preparation.record)
        status = (
            OnlyProjectionApplyStatus.APPLIED
            if preparation.decision is _OnlyProjectionApplyDecision.APPLY
            else OnlyProjectionApplyStatus.RECOVERED
        )
        return self._result(status, context, before, after)

    def _result(
        self,
        status: OnlyProjectionApplyStatus,
        context: OnlyRuntimeProjectionApplyContext,
        before: OnlyDomainModel | None,
        after: OnlyDomainModel | None = None,
    ) -> OnlyProjectionApplyResult:
        identity = context.projection.identity
        result = before if after is None else after
        return OnlyProjectionApplyResult(
            status,
            identity.component,
            identity.entity_key,
            context.execution_sequence,
            _version(before),
            _version(result),
            only_execution_state_hash(before),
            only_execution_state_hash(result),
            identity.payload_hash,
        )


class OnlyFeeReconciliationAuthorityProjectionTarget(_OnlyProjectionTargetBase):
    """Installs one of the append-only reconciliation authorities."""

    def __init__(
        self,
        component: OnlyRuntimeProjectionComponent,
        authority: OnlyFeeReconciliationAuthority,
        applied_ledger: OnlyAppliedRuntimeProjectionLedger,
    ) -> None:
        super().__init__(component, applied_ledger)
        self._authority = authority

    def apply_execution_projection(self, context: OnlyRuntimeProjectionApplyContext) -> OnlyProjectionApplyResult:
        projection = context.projection
        current: OnlyDomainModel | None
        if isinstance(projection, OnlyExternalFeeEvidenceProjection):
            current = self._authority.evidence(projection.identity.entity_key)
        elif isinstance(projection, OnlyFeeReconciliationProjection):
            current = self._authority.decision(projection.identity.entity_key)
        elif isinstance(projection, OnlyFeeAdjustmentProjection):
            current = self._authority.adjustment(projection.identity.entity_key)
        elif isinstance(projection, OnlyUnallocatedExternalFeeProjection):
            current = self._authority.unallocated(projection.after.account_id)
        else:
            return self._result(OnlyProjectionApplyStatus.INVALID_COMPONENT, context, None)
        prepared = self._prepare(context, current)
        if isinstance(prepared, OnlyProjectionApplyResult):
            return prepared
        if prepared.decision is _OnlyProjectionApplyDecision.APPLY:
            if isinstance(projection, OnlyExternalFeeEvidenceProjection):
                self._authority.restore_evidence(projection.after)
            elif isinstance(projection, OnlyFeeReconciliationProjection):
                self._authority.restore_decision(projection.after)
            elif isinstance(projection, OnlyFeeAdjustmentProjection):
                self._authority.restore_adjustment(projection.after)
            else:
                assert isinstance(projection, OnlyUnallocatedExternalFeeProjection)
                self._authority.restore_unallocated(projection.after)
        installed = (
            self._authority.evidence(projection.identity.entity_key)
            if isinstance(projection, OnlyExternalFeeEvidenceProjection)
            else self._authority.decision(projection.identity.entity_key)
            if isinstance(projection, OnlyFeeReconciliationProjection)
            else self._authority.adjustment(projection.identity.entity_key)
            if isinstance(projection, OnlyFeeAdjustmentProjection)
            else self._authority.unallocated(projection.after.account_id)
        )
        assert installed is not None
        return self._complete(context, current, installed, prepared)


class OnlyFeeReconciliationRiskGateProjectionTarget(_OnlyProjectionTargetBase):
    def __init__(
        self,
        authority: OnlyFeeReconciliationRiskGate,
        applied_ledger: OnlyAppliedRuntimeProjectionLedger,
    ) -> None:
        super().__init__(OnlyRuntimeProjectionComponent.RECONCILIATION_RISK_GATE, applied_ledger)
        self._authority = authority

    def apply_execution_projection(self, context: OnlyRuntimeProjectionApplyContext) -> OnlyProjectionApplyResult:
        projection = context.projection
        if not isinstance(projection, OnlyFeeReconciliationRiskGateProjection):
            return self._result(OnlyProjectionApplyStatus.INVALID_COMPONENT, context, None)
        current = self._authority.get(projection.after.account_id)
        prepared = self._prepare(context, current)
        if isinstance(prepared, OnlyProjectionApplyResult):
            return prepared
        if prepared.decision is _OnlyProjectionApplyDecision.APPLY:
            self._authority.restore(projection.after)
        installed = self._authority.get(projection.after.account_id)
        assert installed is not None
        return self._complete(context, current, installed, prepared)


def _order_snapshot(state: OnlyOrderExecutionState) -> OnlyOrderSnapshot:
    return OnlyOrderSnapshot(**{name: getattr(state, name) for name in OnlyOrderSnapshot.__dataclass_fields__})


def _position_snapshot(state: OnlyPositionExecutionState) -> OnlyPositionSnapshot:
    return OnlyPositionSnapshot(**{name: getattr(state, name) for name in OnlyPositionSnapshot.__dataclass_fields__})


def _allocation_snapshot(state: OnlyAllocationExecutionState) -> OnlyPositionAllocationSnapshot:
    return OnlyPositionAllocationSnapshot(
        **{name: getattr(state, name) for name in OnlyPositionAllocationSnapshot.__dataclass_fields__}
    )


class OnlyOrderExecutionProjectionTarget(_OnlyProjectionTargetBase):
    def __init__(self, manager: OnlyOrderManager, applied_ledger: OnlyAppliedRuntimeProjectionLedger) -> None:
        super().__init__(OnlyRuntimeProjectionComponent.ORDER, applied_ledger)
        self._manager = manager

    def apply_execution_projection(self, context: OnlyRuntimeProjectionApplyContext) -> OnlyProjectionApplyResult:
        projection = context.projection
        current_snapshot = (
            self._manager.get_snapshot(projection.after.order_id)
            if isinstance(
                projection,
                OnlyOrderAcceptedExecutionProjection
                | OnlyOrderExecutionProjection
                | OnlyOrderTerminalExecutionProjection,
            )
            else None
        )
        current = None if current_snapshot is None else only_order_execution_state(current_snapshot)
        prepared = self._prepare(context, current)
        if isinstance(prepared, OnlyProjectionApplyResult):
            return prepared
        assert isinstance(
            projection,
            OnlyOrderAcceptedExecutionProjection | OnlyOrderExecutionProjection | OnlyOrderTerminalExecutionProjection,
        )
        snapshot = _order_snapshot(projection.after)
        if not isinstance(
            context.fact,
            OnlyCommittedOrderAcceptedFact | OnlyCommittedExecutionFact | OnlyCommittedTerminalExecutionFact,
        ):
            return self._result(OnlyProjectionApplyStatus.STATE_CONFLICT, context, current)
        external_ids = frozenset({str(context.fact.broker_update_id)})
        trade_ids = (
            frozenset({str(context.fact.trade_id)})
            if isinstance(context.fact, OnlyCommittedExecutionFact)
            else frozenset()
        )
        venue_ids = (
            frozenset(() if context.fact.venue_trade_id is None else {context.fact.venue_trade_id})
            if isinstance(context.fact, OnlyCommittedExecutionFact)
            else frozenset()
        )
        self._manager.restore_execution_authority(
            snapshot,
            external_event_ids=external_ids,
            trade_ids=trade_ids,
            venue_trade_ids=venue_ids,
        )
        if prepared.decision is _OnlyProjectionApplyDecision.APPLY:
            self._manager.restore_execution_event_sequence(self._manager.execution_event_sequence + 1)
        return self._complete(
            context, current, only_order_execution_state(self._manager.require_snapshot(snapshot.order_id)), prepared
        )


class OnlyPositionExecutionProjectionTarget(_OnlyProjectionTargetBase):
    def __init__(self, manager: OnlyPositionManager, applied_ledger: OnlyAppliedRuntimeProjectionLedger) -> None:
        super().__init__(OnlyRuntimeProjectionComponent.POSITION, applied_ledger)
        self._manager = manager

    def apply_execution_projection(self, context: OnlyRuntimeProjectionApplyContext) -> OnlyProjectionApplyResult:
        projection = context.projection
        current_snapshot = (
            self._current(projection) if isinstance(projection, OnlyPositionExecutionProjection) else None
        )
        current = None if current_snapshot is None else only_position_execution_state(current_snapshot)
        prepared = self._prepare(context, current)
        if isinstance(prepared, OnlyProjectionApplyResult):
            return prepared
        assert isinstance(projection, OnlyPositionExecutionProjection)
        snapshot = _position_snapshot(projection.after)
        self._manager.restore_execution_authority(
            snapshot,
            cycle=projection.replay.cycle,
            trade_fingerprints=only_execution_trade_fingerprints(context),
        )
        if prepared.decision is _OnlyProjectionApplyDecision.APPLY:
            self._manager.restore_execution_event_sequence(self._manager.execution_event_sequence + 1)
        installed = self._current(projection)
        if installed is None:
            raise RuntimeError("Position Projection installation lost its entity")
        return self._complete(context, current, only_position_execution_state(installed), prepared)

    def _current(self, projection: OnlyPositionExecutionProjection) -> OnlyPositionSnapshot | None:
        active = self._manager.get_snapshot(projection.after.key)
        if active is not None:
            return active
        return next((item for item in self._manager.closed() if item.position_id == projection.after.position_id), None)


class OnlyAllocationExecutionProjectionTarget(_OnlyProjectionTargetBase):
    def __init__(
        self, manager: OnlyPositionAllocationManager, applied_ledger: OnlyAppliedRuntimeProjectionLedger
    ) -> None:
        super().__init__(OnlyRuntimeProjectionComponent.ALLOCATION, applied_ledger)
        self._manager = manager

    def apply_execution_projection(self, context: OnlyRuntimeProjectionApplyContext) -> OnlyProjectionApplyResult:
        projection = context.projection
        current_snapshot = (
            self._current(projection) if isinstance(projection, OnlyAllocationExecutionProjection) else None
        )
        current = None if current_snapshot is None else only_allocation_execution_state(current_snapshot)
        prepared = self._prepare(context, current)
        if isinstance(prepared, OnlyProjectionApplyResult):
            return prepared
        assert isinstance(projection, OnlyAllocationExecutionProjection)
        snapshot = _allocation_snapshot(projection.after)
        self._manager.restore_execution_authority(
            snapshot,
            cycle=projection.replay.cycle,
            trade_fingerprints=only_execution_trade_fingerprints(context),
        )
        installed = self._current(projection)
        if installed is None:
            raise RuntimeError("Allocation Projection installation lost its entity")
        return self._complete(context, current, only_allocation_execution_state(installed), prepared)

    def _current(self, projection: OnlyAllocationExecutionProjection) -> OnlyPositionAllocationSnapshot | None:
        active = self._manager.get_snapshot(projection.after.key)
        if active is not None:
            return active
        return next(
            (item for item in self._manager.closed() if item.allocation_id == projection.after.allocation_id), None
        )


class OnlySettlementExecutionProjectionTarget(_OnlyProjectionTargetBase):
    def __init__(self, manager: OnlySettlementAuthority, applied_ledger: OnlyAppliedRuntimeProjectionLedger) -> None:
        super().__init__(OnlyRuntimeProjectionComponent.SETTLEMENT, applied_ledger)
        self._manager = manager

    def apply_execution_projection(self, context: OnlyRuntimeProjectionApplyContext) -> OnlyProjectionApplyResult:
        projection = context.projection
        authority = None
        if isinstance(projection, OnlySettlementExecutionProjection):
            instruction = projection.after.instruction
            if instruction is None:
                return self._result(OnlyProjectionApplyStatus.STATE_CONFLICT, context, None)
            try:
                authority = self._manager.require(instruction.instruction_id)
            except KeyError:
                authority = None
        try:
            current = None if authority is None else only_settlement_execution_state(authority)
        except (TypeError, ValueError):
            return self._result(OnlyProjectionApplyStatus.STATE_CONFLICT, context, None)
        prepared = self._prepare(context, current)
        if isinstance(prepared, OnlyProjectionApplyResult):
            return prepared
        assert isinstance(projection, OnlySettlementExecutionProjection)
        after = projection.after
        if after.instruction is None:
            return self._result(OnlyProjectionApplyStatus.STATE_CONFLICT, context, current)
        complete = (
            after.asset_released
            and after.trade_cash_released
            and after.withdrawable_cash_released
            and after.legal_settled
        )
        self._manager.apply_projection(
            authority,
            OnlySettlementInstructionSnapshot(
                after.instruction,
                True,
                after.asset_released,
                True,
                after.trade_cash_released,
                after.withdrawable_cash_released,
                after.legal_settled,
                OnlySettlementInstructionStatus.COMPLETED
                if complete
                else OnlySettlementInstructionStatus.PARTIALLY_EFFECTIVE,
                after.version,
                after.record_sequence_head,
                context.fact.maturity_identity
                if isinstance(context.fact, OnlyCommittedSettlementMaturityFact)
                else None,
            ),
        )
        installed_authority = self._manager.require(after.instruction.instruction_id)
        installed = only_settlement_execution_state(installed_authority)
        return self._complete(context, current, installed, prepared)


class OnlyFeeApplicationProjectionTarget(_OnlyProjectionTargetBase):
    def __init__(self, manager: OnlyFeeApplicationLedger, applied_ledger: OnlyAppliedRuntimeProjectionLedger) -> None:
        super().__init__(OnlyRuntimeProjectionComponent.FEE_LEDGER, applied_ledger)
        self._manager = manager

    def apply_execution_projection(self, context: OnlyRuntimeProjectionApplyContext) -> OnlyProjectionApplyResult:
        projection = context.projection
        if not isinstance(context.fact, OnlyCommittedExecutionFact):
            return self._result(OnlyProjectionApplyStatus.STATE_CONFLICT, context, None)
        authority = (
            self._manager.get(projection.after.application.idempotency_key)
            if isinstance(projection, OnlyFeeApplicationProjection)
            else None
        )
        try:
            current = None if authority is None else only_fee_application_state(authority)
        except (TypeError, ValueError):
            return self._result(OnlyProjectionApplyStatus.STATE_CONFLICT, context, None)
        if authority is not None and authority.instrument_id != context.fact.instrument_id:
            return self._result(OnlyProjectionApplyStatus.STATE_CONFLICT, context, current)
        prepared = self._prepare(context, current)
        if isinstance(prepared, OnlyProjectionApplyResult):
            return prepared
        assert isinstance(projection, OnlyFeeApplicationProjection)
        application = projection.after.application
        self._manager.restore_authority(
            application,
            instrument_id=context.fact.instrument_id,
            records=projection.after.records,
            sequence_head=projection.after.record_sequence_head,
        )
        installed_authority = self._manager.get(application.idempotency_key)
        if installed_authority is None:
            raise RuntimeError("Fee Projection installation lost its instruction")
        return self._complete(context, current, only_fee_application_state(installed_authority), prepared)


class OnlyOrderFeeAccrualProjectionTarget(_OnlyProjectionTargetBase):
    def __init__(self, manager: OnlyOrderFeeAccrualManager, applied_ledger: OnlyAppliedRuntimeProjectionLedger) -> None:
        super().__init__(OnlyRuntimeProjectionComponent.ORDER_FEE_ACCRUAL, applied_ledger)
        self._manager = manager

    def apply_execution_projection(self, context: OnlyRuntimeProjectionApplyContext) -> OnlyProjectionApplyResult:
        projection = context.projection
        if not isinstance(context.fact, OnlyCommittedExecutionFact):
            return self._result(OnlyProjectionApplyStatus.STATE_CONFLICT, context, None)
        current = self._manager.get(context.fact.order_id)
        prepared = self._prepare(context, current)
        if isinstance(prepared, OnlyProjectionApplyResult):
            return prepared
        assert isinstance(projection, OnlyOrderFeeAccrualProjection)
        self._manager.restore(projection.after)
        installed = self._manager.get(projection.after.order_id)
        if installed is None:
            raise RuntimeError("Order fee accrual Projection installation lost its authority")
        return self._complete(context, current, installed, prepared)


def _account_snapshot(state: OnlyAccountExecutionState, current: OnlyAccountSnapshot) -> OnlyAccountSnapshot:
    return OnlyAccountSnapshot(
        state.runtime_id,
        state.account_id,
        state.gateway_id,
        state.account_type,
        state.base_currency,
        state.status,
        OnlyAccountCashBalance(
            state.ledger_cash,
            state.trade_available_cash,
            state.withdrawable_cash,
            state.order_reserved_cash,
            state.unsettled_receivable_cash,
        ),
        state.position_market_value,
        state.realized_pnl,
        state.unrealized_pnl,
        state.fees,
        state.equity,
        current.reservations,
        state.created_at,
        state.updated_at,
        state.valuation_time,
        state.version,
        state.last_external_sequence,
        state.quality_flags,
        state.metadata,
        state.reserved_margin,
        state.occupied_margin,
        state.released_margin,
        state.available_margin,
    )


class OnlyAccountExecutionProjectionTarget(_OnlyProjectionTargetBase):
    def __init__(self, manager: OnlyAccountManager, applied_ledger: OnlyAppliedRuntimeProjectionLedger) -> None:
        super().__init__(OnlyRuntimeProjectionComponent.ACCOUNT, applied_ledger)
        self._manager = manager

    def apply_execution_projection(self, context: OnlyRuntimeProjectionApplyContext) -> OnlyProjectionApplyResult:
        projection = context.projection
        current_snapshot = (
            self._manager.get_snapshot(projection.after.account_id)
            if isinstance(projection, OnlyAccountExecutionProjection)
            else None
        )
        current = None if current_snapshot is None else only_account_execution_state(current_snapshot)
        prepared = self._prepare(context, current)
        if isinstance(prepared, OnlyProjectionApplyResult):
            return prepared
        assert isinstance(projection, OnlyAccountExecutionProjection) and current_snapshot is not None
        trade_ids = (context.fact.trade_id,) if isinstance(context.fact, OnlyCommittedExecutionFact) else ()
        self._manager.restore_execution_authority(
            _account_snapshot(projection.after, current_snapshot),
            trade_ids=trade_ids,
        )
        if prepared.decision is _OnlyProjectionApplyDecision.APPLY:
            self._manager.restore_execution_event_sequence(
                self._manager.execution_event_sequence + (4 if trade_ids else 1)
            )
        installed = self._manager.require_snapshot(projection.after.account_id)
        return self._complete(context, current, only_account_execution_state(installed), prepared)


def _rate(value: Decimal) -> OnlyRate:
    return OnlyRate(value.quantize(Decimal("0.00000001")), 8)


def _ledger_snapshot(
    state: OnlyStrategyLedgerExecutionState,
    current: OnlyStrategyLedgerSnapshot,
    context: OnlyRuntimeProjectionApplyContext,
    projection: OnlyStrategyLedgerExecutionProjection,
) -> OnlyStrategyLedgerSnapshot:
    net = state.realized_pnl + state.unrealized_pnl - state.fees
    quantum = Decimal(1).scaleb(-state.key.base_currency.precision)
    stage_market_amount = (
        sum(
            (
                item.position_market_value.amount
                if item.mark_price.value == 0
                else item.position_market_value.amount / item.mark_price.value * context.fact.fill_price.value
                for item in projection.valuation_lines
            ),
            Decimal(0),
        ).quantize(quantum)
        if isinstance(context.fact, OnlyCommittedExecutionFact)
        else state.position_market_value.amount
    )
    stage_equity = state.ledger_cash.amount + stage_market_amount
    stage_high = max(current.equity.high_water_mark.amount, stage_equity)
    stage_drawdown = Decimal(0) if stage_high == 0 else stage_equity / stage_high - Decimal(1)
    high_amount = max(stage_high, state.equity.amount)
    high = OnlyMoney(high_amount, state.key.base_currency)
    drawdown = _rate(Decimal(0) if high.amount == 0 else state.equity.amount / high.amount - Decimal(1))
    maximum_value = min(current.equity.maximum_drawdown.value, stage_drawdown, drawdown.value)
    maximum = (
        current.equity.maximum_drawdown
        if current.equity.maximum_drawdown.value == maximum_value
        else _rate(maximum_value)
    )
    simple = None
    if state.external_cash_flow.amount == 0 and state.initial_capital.amount > 0:
        simple = _rate((state.equity.amount - state.initial_capital.amount) / state.initial_capital.amount)
    cash = OnlyStrategyCashSnapshot(state.ledger_cash, state.cash_reserved, state.cash_available)
    pnl = OnlyStrategyPnLSnapshot(state.realized_pnl, state.unrealized_pnl, state.fees, net)
    equity = replace(
        current.equity,
        ts_event=state.updated_at,
        ts_init=state.updated_at,
        trading_day=state.trading_day,
        version=state.version,
        initial_capital=state.initial_capital,
        external_cash_flow=state.external_cash_flow,
        ledger_cash=state.ledger_cash,
        cash_reserved=state.cash_reserved,
        cash_available=state.cash_available,
        position_cost=state.position_cost,
        position_market_value=state.position_market_value,
        realized_pnl=state.realized_pnl,
        unrealized_pnl=state.unrealized_pnl,
        fees=state.fees,
        net_pnl=net,
        equity=state.equity,
        equity_by_cash_view=state.ledger_cash + state.position_market_value,
        equity_by_pnl_view=state.initial_capital + state.external_cash_flow + net,
        high_water_mark=high,
        drawdown=drawdown,
        maximum_drawdown=maximum,
        return_since_start=simple,
        daily_pnl=state.equity - current.equity.equity + current.equity.daily_pnl,
        quality_flags=state.quality_flags,
    )
    performance = replace(
        current.performance,
        ts_event=state.updated_at,
        equity=state.equity,
        net_pnl=net,
        return_since_start=simple,
        daily_pnl=equity.daily_pnl,
        daily_return=equity.daily_return,
        drawdown=drawdown,
        maximum_drawdown=maximum,
        trade_count=current.performance.trade_count + int(isinstance(context.fact, OnlyCommittedExecutionFact)),
        fees=state.fees,
    )
    return replace(
        current,
        status=state.status,
        capital=replace(
            current.capital,
            initial_capital=state.initial_capital,
            external_cash_flow=state.external_cash_flow,
            as_of=state.updated_at,
            version=state.version,
        ),
        cash=cash,
        pnl=pnl,
        equity=equity,
        performance=performance,
        cash_entries=state.cash_entries,
        fee_entries=state.fee_entries,
        updated_at=state.updated_at,
        valuation_time=state.valuation_time,
        version=state.version,
        last_trade_sequence=state.last_trade_sequence,
        last_trade_order=state.last_trade_order,
        quality_flags=state.quality_flags,
    )


class OnlyStrategyLedgerExecutionProjectionTarget(_OnlyProjectionTargetBase):
    def __init__(self, manager: OnlyStrategyLedgerManager, applied_ledger: OnlyAppliedRuntimeProjectionLedger) -> None:
        super().__init__(OnlyRuntimeProjectionComponent.STRATEGY_LEDGER, applied_ledger)
        self._manager = manager

    def apply_execution_projection(self, context: OnlyRuntimeProjectionApplyContext) -> OnlyProjectionApplyResult:
        projection = context.projection
        current_snapshot = (
            self._manager.get_snapshot(projection.after.key)
            if isinstance(projection, OnlyStrategyLedgerExecutionProjection)
            else None
        )
        current = None if current_snapshot is None else only_strategy_ledger_execution_state(current_snapshot)
        prepared = self._prepare(context, current)
        if isinstance(prepared, OnlyProjectionApplyResult):
            return prepared
        assert isinstance(projection, OnlyStrategyLedgerExecutionProjection) and current_snapshot is not None
        snapshot = (
            _ledger_snapshot(projection.after, current_snapshot, context, projection)
            if prepared.decision is _OnlyProjectionApplyDecision.APPLY
            else current_snapshot
        )
        if only_strategy_ledger_execution_state(snapshot) != projection.after:
            raise ValueError("Strategy Ledger install plan does not reproduce committed authority")
        if prepared.decision is _OnlyProjectionApplyDecision.APPLY:
            self._manager.restore_execution_authority(
                snapshot,
                trade_fingerprints=only_execution_trade_fingerprints(context),
                valuation_lines=projection.valuation_lines,
            )
        else:
            self._manager.restore_execution_indexes(
                snapshot,
                trade_fingerprints=only_execution_trade_fingerprints(context),
                valuation_lines=projection.valuation_lines,
            )
        if prepared.decision is _OnlyProjectionApplyDecision.APPLY:
            self._manager.restore_execution_event_sequence(
                self._manager.execution_event_sequence
                + (4 if isinstance(context.fact, OnlyCommittedExecutionFact) else 1)
            )
        installed = self._manager.require_snapshot(projection.after.key)
        return self._complete(context, current, only_strategy_ledger_execution_state(installed), prepared)


class OnlyAccountCashReservationExecutionProjectionTarget(_OnlyProjectionTargetBase):
    def __init__(self, manager: OnlyAccountManager, applied_ledger: OnlyAppliedRuntimeProjectionLedger) -> None:
        super().__init__(OnlyRuntimeProjectionComponent.ACCOUNT_CASH_RESERVATION, applied_ledger)
        self._manager = manager

    def apply_execution_projection(self, context: OnlyRuntimeProjectionApplyContext) -> OnlyProjectionApplyResult:
        projection = context.projection
        current_entity = None
        if isinstance(projection, OnlyAccountCashReservationExecutionProjection):
            current_entity = self._manager.get_cash_reservation(
                OnlyAccountReservationId(projection.after.reservation_id)
            )
        current = None if current_entity is None else only_account_cash_reservation_execution_state(current_entity)
        prepared = self._prepare(context, current)
        if isinstance(prepared, OnlyProjectionApplyResult):
            return prepared
        assert isinstance(projection, OnlyAccountCashReservationExecutionProjection)
        state = projection.after
        reservation = OnlyAccountReservation(
            OnlyAccountReservationId(state.reservation_id),
            state.runtime_id,
            state.account_id,
            state.order_id,
            state.reserved_amount,
            state.consumed_amount,
            state.remaining_amount,
            state.state,
            state.created_at,
            state.updated_at,
            state.version,
        )
        self._manager.restore_cash_reservation_execution_authority(reservation)
        return self._complete(context, current, only_account_cash_reservation_execution_state(reservation), prepared)


class OnlyStrategyCashReservationExecutionProjectionTarget(_OnlyProjectionTargetBase):
    def __init__(self, manager: OnlyStrategyLedgerManager, applied_ledger: OnlyAppliedRuntimeProjectionLedger) -> None:
        super().__init__(OnlyRuntimeProjectionComponent.STRATEGY_CASH_RESERVATION, applied_ledger)
        self._manager = manager

    def apply_execution_projection(self, context: OnlyRuntimeProjectionApplyContext) -> OnlyProjectionApplyResult:
        projection = context.projection
        current_entity = None
        if isinstance(projection, OnlyStrategyCashReservationExecutionProjection):
            current_entity = self._manager.get_cash_reservation(projection.after.key, projection.after.order_id)
        current = None if current_entity is None else only_strategy_cash_reservation_execution_state(current_entity)
        prepared = self._prepare(context, current)
        if isinstance(prepared, OnlyProjectionApplyResult):
            return prepared
        assert isinstance(projection, OnlyStrategyCashReservationExecutionProjection)
        state = projection.after
        reservation = OnlyStrategyCashReservation(
            state.reservation_id,
            state.key,
            state.order_id,
            state.estimated_notional,
            state.estimated_fee,
            state.reserved_amount,
            state.consumed_amount,
            state.remaining_amount,
            state.state,
            state.stage,
            state.created_at,
            state.updated_at,
            state.version,
            state.metadata,
        )
        self._manager.restore_cash_reservation_execution_authority(reservation)
        return self._complete(context, current, only_strategy_cash_reservation_execution_state(reservation), prepared)


class OnlyPositionReservationExecutionProjectionTarget(_OnlyProjectionTargetBase):
    def __init__(
        self, manager: OnlyPositionReservationManager, applied_ledger: OnlyAppliedRuntimeProjectionLedger
    ) -> None:
        super().__init__(OnlyRuntimeProjectionComponent.POSITION_RESERVATION, applied_ledger)
        self._manager = manager

    def apply_execution_projection(self, context: OnlyRuntimeProjectionApplyContext) -> OnlyProjectionApplyResult:
        projection = context.projection
        current_entity = (
            self._manager.get(projection.after.order_id)
            if isinstance(projection, OnlyPositionReservationExecutionProjection)
            else None
        )
        current = None if current_entity is None else only_position_reservation_execution_state(current_entity)
        prepared = self._prepare(context, current)
        if isinstance(prepared, OnlyProjectionApplyResult):
            return prepared
        assert isinstance(projection, OnlyPositionReservationExecutionProjection)
        state: OnlyPositionReservationExecutionState = projection.after
        reservation = OnlyPositionReservation(
            **{name: getattr(state, name) for name in OnlyPositionReservation.__dataclass_fields__}
        )
        self._manager.restore_execution_authority(reservation)
        return self._complete(context, current, only_position_reservation_execution_state(reservation), prepared)


class OnlyRiskReservationExecutionProjectionTarget(_OnlyProjectionTargetBase):
    def __init__(self, service: OnlyRiskService, applied_ledger: OnlyAppliedRuntimeProjectionLedger) -> None:
        super().__init__(OnlyRuntimeProjectionComponent.RISK_RESERVATION, applied_ledger)
        self._service = service

    def apply_execution_projection(self, context: OnlyRuntimeProjectionApplyContext) -> OnlyProjectionApplyResult:
        projection = context.projection
        current_entity = (
            self._service.reservations.get_for_order(projection.after.order_id)
            if isinstance(projection, OnlyRiskReservationExecutionProjection)
            else None
        )
        current = None if current_entity is None else only_risk_reservation_execution_state(current_entity)
        prepared = self._prepare(context, current)
        if isinstance(prepared, OnlyProjectionApplyResult):
            return prepared
        assert isinstance(projection, OnlyRiskReservationExecutionProjection)
        state = projection.after
        reservation = OnlyRiskReservation(
            state.reservation_id,
            state.reservation_type,
            state.runtime_id,
            state.cluster_id,
            state.account_id,
            state.order_id,
            state.instrument_id,
            state.reserved_notional,
            state.reserved_quantity,
            state.created_at,
            state.updated_at,
            state.state,
            state.version,
            state.release_reason,
            state.consumed_notional,
            state.consumed_quantity,
            state.released_notional,
            state.released_quantity,
        )
        sequence = max(self._service.reservations.sequence_head, 1)
        self._service.reservations.restore_execution_authority(reservation, sequence=sequence)
        return self._complete(context, current, only_risk_reservation_execution_state(reservation), prepared)


class OnlyRiskExecutionProjectionTarget(_OnlyProjectionTargetBase):
    def __init__(self, service: OnlyRiskService, applied_ledger: OnlyAppliedRuntimeProjectionLedger) -> None:
        super().__init__(OnlyRuntimeProjectionComponent.RISK, applied_ledger)
        self._service = service

    def apply_execution_projection(self, context: OnlyRuntimeProjectionApplyContext) -> OnlyProjectionApplyResult:
        projection = context.projection
        current_snapshot = (
            self._service.get_snapshot(projection.after.cluster_id)
            if isinstance(projection, OnlyRiskExecutionProjection)
            else None
        )
        current = None if current_snapshot is None else only_risk_execution_state(current_snapshot)
        prepared = self._prepare(context, current)
        if isinstance(prepared, OnlyProjectionApplyResult):
            return prepared
        assert isinstance(projection, OnlyRiskExecutionProjection)
        state = projection.after
        snapshot = OnlyRiskSnapshot(**{name: getattr(state, name) for name in OnlyRiskSnapshot.__dataclass_fields__})
        self._service.restore_execution_authority(snapshot)
        if prepared.decision is _OnlyProjectionApplyDecision.APPLY:
            self._service.restore_execution_event_sequence(self._service.execution_event_sequence + 1)
        return self._complete(context, current, only_risk_execution_state(snapshot), prepared)


class OnlyExecutionValuationAuthority:
    """Runtime valuation version authority used by PR3 and future PR4 assembly."""

    def __init__(
        self,
        states: Mapping[OnlyAccountId, OnlyValuationExecutionState] | None = None,
        account_performance: OnlyAccountPerformanceProjector | None = None,
        runtime_state_restorer: Callable[[OnlyValuationExecutionState], None] | None = None,
        runtime_state_provider: Callable[[OnlyAccountId], OnlyValuationExecutionState | None] | None = None,
    ) -> None:
        self._states = {} if states is None else dict(states)
        self._account_performance = account_performance
        self._runtime_state_restorer = runtime_state_restorer
        self._runtime_state_provider = runtime_state_provider

    def get(self, account_id: OnlyAccountId) -> OnlyValuationExecutionState | None:
        if self._runtime_state_provider is not None:
            return self._runtime_state_provider(account_id)
        return self._states.get(account_id)

    def restore(self, state: OnlyValuationExecutionState) -> None:
        self._states[state.account_id] = state
        if self._runtime_state_restorer is not None:
            self._runtime_state_restorer(state)

    def restore_account_equity_points(self, projection: OnlyValuationExecutionProjection) -> None:
        if projection.account_equity_points:
            if self._account_performance is None:
                raise ValueError("Valuation replay requires the Runtime Account performance projector")
            self._account_performance.restore_execution_points(projection.account_equity_points)

    def validate_account_equity_points(self, projection: OnlyValuationExecutionProjection) -> None:
        if projection.account_equity_points:
            if self._account_performance is None:
                raise ValueError("Valuation replay requires the Runtime Account performance projector")
            self._account_performance.validate_execution_points(projection.account_equity_points)


class OnlyValuationExecutionProjectionTarget(_OnlyProjectionTargetBase):
    def __init__(
        self,
        authority: OnlyExecutionValuationAuthority,
        account_manager: OnlyAccountManager,
        ledger_manager: OnlyStrategyLedgerManager,
        applied_ledger: OnlyAppliedRuntimeProjectionLedger,
    ) -> None:
        super().__init__(OnlyRuntimeProjectionComponent.VALUATION, applied_ledger)
        self._authority = authority
        self._accounts = account_manager
        self._ledgers = ledger_manager

    def apply_execution_projection(self, context: OnlyRuntimeProjectionApplyContext) -> OnlyProjectionApplyResult:
        projection = context.projection
        current = (
            self._authority.get(projection.after.account_id)
            if isinstance(projection, OnlyValuationExecutionProjection)
            else None
        )
        prepared = self._prepare(context, current)
        if isinstance(prepared, OnlyProjectionApplyResult):
            return prepared
        assert isinstance(projection, OnlyValuationExecutionProjection)
        self._authority.validate_account_equity_points(projection)
        self._ledgers.validate_execution_equity_points(projection.strategy_equity_points)
        self._authority.restore(projection.after)
        self._authority.restore_account_equity_points(projection)
        self._ledgers.restore_execution_equity_points(projection.strategy_equity_points)
        self._accounts.restore_valuation_version(projection.after.account_id, projection.after.version)
        for snapshot in self._ledgers.list_ledgers():
            if snapshot.key.account_id == projection.after.account_id:
                self._ledgers.restore_valuation_version(snapshot.key, projection.after.version)
        return self._complete(context, current, projection.after, prepared)


def only_create_generic_t0_execution_projection_targets(
    *,
    order_manager: OnlyOrderManager,
    position_manager: OnlyPositionManager,
    allocation_manager: OnlyPositionAllocationManager,
    position_reservation_manager: OnlyPositionReservationManager,
    settlement_authority: OnlySettlementAuthority,
    fee_application_ledger: OnlyFeeApplicationLedger,
    order_fee_accrual_manager: OnlyOrderFeeAccrualManager,
    account_manager: OnlyAccountManager,
    ledger_manager: OnlyStrategyLedgerManager,
    risk_service: OnlyRiskService,
    valuation_authority: OnlyExecutionValuationAuthority,
    applied_ledger: OnlyAppliedRuntimeProjectionLedger,
    fee_reconciliation_authority: OnlyFeeReconciliationAuthority | None = None,
    fee_reconciliation_risk_gate: OnlyFeeReconciliationRiskGate | None = None,
) -> Mapping[OnlyRuntimeProjectionComponent, OnlyRuntimeProjectionTarget]:
    targets: tuple[OnlyRuntimeProjectionTarget, ...] = (
        OnlyOrderExecutionProjectionTarget(order_manager, applied_ledger),
        OnlyPositionExecutionProjectionTarget(position_manager, applied_ledger),
        OnlyAllocationExecutionProjectionTarget(allocation_manager, applied_ledger),
        OnlySettlementExecutionProjectionTarget(settlement_authority, applied_ledger),
        OnlyFeeApplicationProjectionTarget(fee_application_ledger, applied_ledger),
        OnlyOrderFeeAccrualProjectionTarget(order_fee_accrual_manager, applied_ledger),
        OnlyAccountExecutionProjectionTarget(account_manager, applied_ledger),
        OnlyStrategyLedgerExecutionProjectionTarget(ledger_manager, applied_ledger),
        OnlyAccountCashReservationExecutionProjectionTarget(account_manager, applied_ledger),
        OnlyStrategyCashReservationExecutionProjectionTarget(ledger_manager, applied_ledger),
        OnlyPositionReservationExecutionProjectionTarget(position_reservation_manager, applied_ledger),
        OnlyRiskReservationExecutionProjectionTarget(risk_service, applied_ledger),
        OnlyRiskExecutionProjectionTarget(risk_service, applied_ledger),
        OnlyValuationExecutionProjectionTarget(
            valuation_authority,
            account_manager,
            ledger_manager,
            applied_ledger,
        ),
    )
    if fee_reconciliation_authority is not None and fee_reconciliation_risk_gate is not None:
        targets += tuple(
            OnlyFeeReconciliationAuthorityProjectionTarget(component, fee_reconciliation_authority, applied_ledger)
            for component in (
                OnlyRuntimeProjectionComponent.EXTERNAL_FEE_EVIDENCE,
                OnlyRuntimeProjectionComponent.FEE_RECONCILIATION,
                OnlyRuntimeProjectionComponent.FEE_ADJUSTMENT_LEDGER,
                OnlyRuntimeProjectionComponent.UNALLOCATED_EXTERNAL_FEE,
            )
        )
        targets += (OnlyFeeReconciliationRiskGateProjectionTarget(fee_reconciliation_risk_gate, applied_ledger),)
    result = {target.component: target for target in targets}
    expected = 19 if fee_reconciliation_authority is not None else 14
    if len(result) != expected:
        raise RuntimeError("Generic T0 Projection Target registry is incomplete or duplicated")
    return result


__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("only_")]
