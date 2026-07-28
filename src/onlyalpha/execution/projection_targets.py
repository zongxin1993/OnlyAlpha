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
from onlyalpha.fee.manager import OnlyFeeManager
from onlyalpha.fee.models import OnlyFeeInstruction
from onlyalpha.market.runtime_rules import OnlySettlementRuntimeInstruction
from onlyalpha.order.manager import OnlyOrderManager
from onlyalpha.position.allocation_manager import OnlyPositionAllocationManager
from onlyalpha.position.manager import OnlyPositionManager
from onlyalpha.position.models import OnlyPositionAllocationSnapshot, OnlyPositionSnapshot
from onlyalpha.risk.reservations import OnlyRiskReservation
from onlyalpha.risk.service import OnlyRiskService
from onlyalpha.risk.snapshots import OnlyRiskSnapshot
from onlyalpha.settlement.manager import OnlySettlementManager, OnlySettlementRecord
from onlyalpha.strategy_ledger.manager import OnlyStrategyLedgerManager
from onlyalpha.strategy_ledger.models import (
    OnlyStrategyCashReservation,
    OnlyStrategyCashSnapshot,
    OnlyStrategyLedgerSnapshot,
    OnlyStrategyPnLSnapshot,
)

from .applied_projection import (
    OnlyAppliedProjectionLedger,
    OnlyAppliedProjectionRecord,
    OnlyExecutionProjectionApplyContext,
)
from .authority_state import (
    only_fee_execution_state,
    only_settlement_execution_state,
    only_settlement_record_replay,
)
from .execution_state import (
    OnlyAccountExecutionState,
    OnlyAllocationExecutionState,
    OnlyOrderExecutionState,
    OnlyPositionExecutionState,
    OnlyStrategyLedgerExecutionState,
    only_account_cash_reservation_execution_state,
    only_account_execution_state,
    only_allocation_execution_state,
    only_order_execution_state,
    only_position_execution_state,
    only_risk_execution_state,
    only_risk_reservation_execution_state,
    only_strategy_cash_reservation_execution_state,
    only_strategy_ledger_execution_state,
)
from .projection import (
    OnlyAccountCashReservationExecutionProjection,
    OnlyAccountExecutionProjection,
    OnlyAllocationExecutionProjection,
    OnlyExecutionProjectionComponent,
    OnlyExecutionProjectionTarget,
    OnlyFeeExecutionProjection,
    OnlyOrderExecutionProjection,
    OnlyPositionExecutionProjection,
    OnlyProjectionApplyResult,
    OnlyProjectionApplyStatus,
    OnlyRiskExecutionProjection,
    OnlyRiskReservationExecutionProjection,
    OnlySettlementExecutionProjection,
    OnlyStrategyCashReservationExecutionProjection,
    OnlyStrategyLedgerExecutionProjection,
    OnlyValuationExecutionProjection,
    OnlyValuationExecutionState,
)
from .state_hash import only_execution_state_hash


def only_execution_trade_fingerprints(context: OnlyExecutionProjectionApplyContext) -> tuple[str, ...]:
    fact = context.fact
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
    record: OnlyAppliedProjectionRecord


class _OnlyProjectionTargetBase:
    def __init__(
        self,
        component: OnlyExecutionProjectionComponent,
        applied_ledger: OnlyAppliedProjectionLedger,
    ) -> None:
        self._component = component
        self._applied_ledger = applied_ledger

    @property
    def component(self) -> OnlyExecutionProjectionComponent:
        return self._component

    def _prepare(
        self,
        context: OnlyExecutionProjectionApplyContext,
        current: OnlyDomainModel | None,
    ) -> OnlyProjectionApplyResult | _OnlyProjectionApplyPreparation:
        identity = context.projection.identity
        if identity.component is not self.component:
            return self._result(OnlyProjectionApplyStatus.INVALID_COMPONENT, context, current)
        prior = self._applied_ledger.get(context.execution_sequence, self.component)
        record = OnlyAppliedProjectionRecord(
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
        context: OnlyExecutionProjectionApplyContext,
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
        context: OnlyExecutionProjectionApplyContext,
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


def _order_snapshot(state: OnlyOrderExecutionState) -> OnlyOrderSnapshot:
    return OnlyOrderSnapshot(**{name: getattr(state, name) for name in OnlyOrderSnapshot.__dataclass_fields__})


def _position_snapshot(state: OnlyPositionExecutionState) -> OnlyPositionSnapshot:
    return OnlyPositionSnapshot(**{name: getattr(state, name) for name in OnlyPositionSnapshot.__dataclass_fields__})


def _allocation_snapshot(state: OnlyAllocationExecutionState) -> OnlyPositionAllocationSnapshot:
    return OnlyPositionAllocationSnapshot(
        **{name: getattr(state, name) for name in OnlyPositionAllocationSnapshot.__dataclass_fields__}
    )


class OnlyOrderExecutionProjectionTarget(_OnlyProjectionTargetBase):
    def __init__(self, manager: OnlyOrderManager, applied_ledger: OnlyAppliedProjectionLedger) -> None:
        super().__init__(OnlyExecutionProjectionComponent.ORDER, applied_ledger)
        self._manager = manager

    def apply_execution_projection(self, context: OnlyExecutionProjectionApplyContext) -> OnlyProjectionApplyResult:
        projection = context.projection
        current_snapshot = (
            self._manager.get_snapshot(projection.after.order_id)
            if isinstance(projection, OnlyOrderExecutionProjection)
            else None
        )
        current = None if current_snapshot is None else only_order_execution_state(current_snapshot)
        prepared = self._prepare(context, current)
        if isinstance(prepared, OnlyProjectionApplyResult):
            return prepared
        assert isinstance(projection, OnlyOrderExecutionProjection)
        snapshot = _order_snapshot(projection.after)
        external_ids = frozenset({str(context.fact.broker_update_id)})
        trade_ids = frozenset({str(context.fact.trade_id)})
        venue_ids = frozenset(() if context.fact.venue_trade_id is None else {context.fact.venue_trade_id})
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
    def __init__(self, manager: OnlyPositionManager, applied_ledger: OnlyAppliedProjectionLedger) -> None:
        super().__init__(OnlyExecutionProjectionComponent.POSITION, applied_ledger)
        self._manager = manager

    def apply_execution_projection(self, context: OnlyExecutionProjectionApplyContext) -> OnlyProjectionApplyResult:
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
    def __init__(self, manager: OnlyPositionAllocationManager, applied_ledger: OnlyAppliedProjectionLedger) -> None:
        super().__init__(OnlyExecutionProjectionComponent.ALLOCATION, applied_ledger)
        self._manager = manager

    def apply_execution_projection(self, context: OnlyExecutionProjectionApplyContext) -> OnlyProjectionApplyResult:
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
    def __init__(self, manager: OnlySettlementManager, applied_ledger: OnlyAppliedProjectionLedger) -> None:
        super().__init__(OnlyExecutionProjectionComponent.SETTLEMENT, applied_ledger)
        self._manager = manager

    def apply_execution_projection(self, context: OnlyExecutionProjectionApplyContext) -> OnlyProjectionApplyResult:
        projection = context.projection
        authority = (
            self._manager.get_execution_authority(projection.after.instruction_id)
            if isinstance(projection, OnlySettlementExecutionProjection)
            else None
        )
        if authority is not None and authority.cash_currency is None:
            return self._result(OnlyProjectionApplyStatus.STATE_CONFLICT, context, None)
        try:
            current = None if authority is None else only_settlement_execution_state(authority)
        except (TypeError, ValueError):
            return self._result(OnlyProjectionApplyStatus.STATE_CONFLICT, context, None)
        prepared = self._prepare(context, current)
        if isinstance(prepared, OnlyProjectionApplyResult):
            return prepared
        assert isinstance(projection, OnlySettlementExecutionProjection)
        if authority is not None and only_settlement_record_replay(authority) != projection.records:
            return self._result(OnlyProjectionApplyStatus.STATE_CONFLICT, context, current)
        after = projection.after
        instruction = OnlySettlementRuntimeInstruction(
            after.instruction_id,
            str(after.instrument_id),
            after.source_trade_id,
            after.asset_quantity,
            after.cash_amount.amount,
            after.asset_available_on,
            after.cash_trade_available_on,
            after.cash_withdrawable_on,
            after.legal_settlement_on,
            str(after.account_id),
            str(after.source_order_id),
        )
        records = tuple(
            OnlySettlementRecord(
                item.instruction_id,
                str(item.instrument_id),
                item.source_trade_id,
                after.asset_quantity,
                after.cash_amount.amount,
                after.asset_quantity,
                item.available_quantity,
                item.trade_available_cash.amount,
                item.withdrawable_cash.amount,
                item.legal_settled,
                item.processed_on,
                item.sequence,
                str(item.account_id),
                str(item.source_order_id),
                after.legal_settlement_on,
                "SETTLED" if item.legal_settled else "PENDING",
            )
            for item in projection.records
        )
        self._manager.restore_execution_authority(
            instruction,
            asset_released=after.asset_released,
            trade_cash_released=after.trade_cash_released,
            withdrawable_cash_released=after.withdrawable_cash_released,
            legal_settled=after.legal_settled,
            records=records,
            sequence_head=after.record_sequence_head,
            version=after.version,
            cash_currency=after.cash_amount.currency,
        )
        installed_authority = self._manager.get_execution_authority(after.instruction_id)
        if installed_authority is None:
            raise RuntimeError("Settlement Projection installation lost its instruction")
        installed = only_settlement_execution_state(installed_authority)
        if only_settlement_record_replay(installed_authority) != projection.records:
            raise RuntimeError("Settlement Projection installation produced the wrong records")
        return self._complete(context, current, installed, prepared)


class OnlyFeeExecutionProjectionTarget(_OnlyProjectionTargetBase):
    def __init__(self, manager: OnlyFeeManager, applied_ledger: OnlyAppliedProjectionLedger) -> None:
        super().__init__(OnlyExecutionProjectionComponent.FEE, applied_ledger)
        self._manager = manager

    def apply_execution_projection(self, context: OnlyExecutionProjectionApplyContext) -> OnlyProjectionApplyResult:
        projection = context.projection
        authority = (
            self._manager.get_execution_authority(projection.after.instruction.idempotency_key)
            if isinstance(projection, OnlyFeeExecutionProjection)
            else None
        )
        try:
            current = None if authority is None else only_fee_execution_state(authority)
        except (TypeError, ValueError):
            return self._result(OnlyProjectionApplyStatus.STATE_CONFLICT, context, None)
        if authority is not None and authority.instrument_id != str(context.fact.instrument_id):
            return self._result(OnlyProjectionApplyStatus.STATE_CONFLICT, context, current)
        prepared = self._prepare(context, current)
        if isinstance(prepared, OnlyProjectionApplyResult):
            return prepared
        assert isinstance(projection, OnlyFeeExecutionProjection)
        replay = projection.after.instruction
        instruction = OnlyFeeInstruction(
            replay.instruction_id,
            replay.runtime_id,
            replay.cluster_id,
            replay.account_id,
            replay.order_id,
            replay.trade_id,
            projection.after.fee_breakdown,
            replay.calculation_source,
            replay.created_at.to_datetime(),
            replay.idempotency_key,
        )
        self._manager.restore_execution_authority(
            instruction,
            instrument_id=str(context.fact.instrument_id),
            record_ids=tuple(item.record_id for item in projection.after.records),
            sequence_head=projection.after.record_sequence_head,
        )
        installed_authority = self._manager.get_execution_authority(replay.idempotency_key)
        if installed_authority is None:
            raise RuntimeError("Fee Projection installation lost its instruction")
        return self._complete(context, current, only_fee_execution_state(installed_authority), prepared)


def _account_snapshot(state: OnlyAccountExecutionState, current: OnlyAccountSnapshot) -> OnlyAccountSnapshot:
    return OnlyAccountSnapshot(
        state.runtime_id,
        state.account_id,
        state.gateway_id,
        state.account_type,
        state.base_currency,
        state.status,
        OnlyAccountCashBalance(state.cash_balance, state.available_cash, state.frozen_cash, state.unsettled_cash),
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
    def __init__(self, manager: OnlyAccountManager, applied_ledger: OnlyAppliedProjectionLedger) -> None:
        super().__init__(OnlyExecutionProjectionComponent.ACCOUNT, applied_ledger)
        self._manager = manager

    def apply_execution_projection(self, context: OnlyExecutionProjectionApplyContext) -> OnlyProjectionApplyResult:
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
        self._manager.restore_execution_authority(
            _account_snapshot(projection.after, current_snapshot),
            trade_ids=(context.fact.trade_id,),
        )
        if prepared.decision is _OnlyProjectionApplyDecision.APPLY:
            self._manager.restore_execution_event_sequence(self._manager.execution_event_sequence + 4)
        installed = self._manager.require_snapshot(projection.after.account_id)
        return self._complete(context, current, only_account_execution_state(installed), prepared)


def _rate(value: Decimal) -> OnlyRate:
    return OnlyRate(value.quantize(Decimal("0.00000001")), 8)


def _ledger_snapshot(
    state: OnlyStrategyLedgerExecutionState,
    current: OnlyStrategyLedgerSnapshot,
    context: OnlyExecutionProjectionApplyContext,
    projection: OnlyStrategyLedgerExecutionProjection,
) -> OnlyStrategyLedgerSnapshot:
    net = state.realized_pnl + state.unrealized_pnl - state.fees
    quantum = Decimal(1).scaleb(-state.key.base_currency.precision)
    stage_market_amount = sum(
        (
            item.position_market_value.amount
            if item.mark_price.value == 0
            else item.position_market_value.amount / item.mark_price.value * context.fact.fill_price.value
            for item in projection.valuation_lines
        ),
        Decimal(0),
    ).quantize(quantum)
    stage_equity = state.cash_balance.amount + stage_market_amount
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
    cash = OnlyStrategyCashSnapshot(state.cash_balance, state.cash_reserved, state.cash_available)
    pnl = OnlyStrategyPnLSnapshot(state.realized_pnl, state.unrealized_pnl, state.fees, net)
    equity = replace(
        current.equity,
        ts_event=state.updated_at,
        ts_init=state.updated_at,
        version=state.version,
        initial_capital=state.initial_capital,
        external_cash_flow=state.external_cash_flow,
        cash_balance=state.cash_balance,
        cash_reserved=state.cash_reserved,
        cash_available=state.cash_available,
        position_cost=state.position_cost,
        position_market_value=state.position_market_value,
        realized_pnl=state.realized_pnl,
        unrealized_pnl=state.unrealized_pnl,
        fees=state.fees,
        net_pnl=net,
        equity=state.equity,
        equity_by_cash_view=state.cash_balance + state.position_market_value,
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
        trade_count=current.performance.trade_count + 1,
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
    def __init__(self, manager: OnlyStrategyLedgerManager, applied_ledger: OnlyAppliedProjectionLedger) -> None:
        super().__init__(OnlyExecutionProjectionComponent.STRATEGY_LEDGER, applied_ledger)
        self._manager = manager

    def apply_execution_projection(self, context: OnlyExecutionProjectionApplyContext) -> OnlyProjectionApplyResult:
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
            self._manager.restore_execution_event_sequence(self._manager.execution_event_sequence + 4)
        installed = self._manager.require_snapshot(projection.after.key)
        return self._complete(context, current, only_strategy_ledger_execution_state(installed), prepared)


class OnlyAccountCashReservationExecutionProjectionTarget(_OnlyProjectionTargetBase):
    def __init__(self, manager: OnlyAccountManager, applied_ledger: OnlyAppliedProjectionLedger) -> None:
        super().__init__(OnlyExecutionProjectionComponent.ACCOUNT_CASH_RESERVATION, applied_ledger)
        self._manager = manager

    def apply_execution_projection(self, context: OnlyExecutionProjectionApplyContext) -> OnlyProjectionApplyResult:
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
    def __init__(self, manager: OnlyStrategyLedgerManager, applied_ledger: OnlyAppliedProjectionLedger) -> None:
        super().__init__(OnlyExecutionProjectionComponent.STRATEGY_CASH_RESERVATION, applied_ledger)
        self._manager = manager

    def apply_execution_projection(self, context: OnlyExecutionProjectionApplyContext) -> OnlyProjectionApplyResult:
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


class OnlyRiskReservationExecutionProjectionTarget(_OnlyProjectionTargetBase):
    def __init__(self, service: OnlyRiskService, applied_ledger: OnlyAppliedProjectionLedger) -> None:
        super().__init__(OnlyExecutionProjectionComponent.RISK_RESERVATION, applied_ledger)
        self._service = service

    def apply_execution_projection(self, context: OnlyExecutionProjectionApplyContext) -> OnlyProjectionApplyResult:
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
        )
        sequence = max(self._service.reservations.sequence_head, 1)
        self._service.reservations.restore_execution_authority(reservation, sequence=sequence)
        return self._complete(context, current, only_risk_reservation_execution_state(reservation), prepared)


class OnlyRiskExecutionProjectionTarget(_OnlyProjectionTargetBase):
    def __init__(self, service: OnlyRiskService, applied_ledger: OnlyAppliedProjectionLedger) -> None:
        super().__init__(OnlyExecutionProjectionComponent.RISK, applied_ledger)
        self._service = service

    def apply_execution_projection(self, context: OnlyExecutionProjectionApplyContext) -> OnlyProjectionApplyResult:
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
        applied_ledger: OnlyAppliedProjectionLedger,
    ) -> None:
        super().__init__(OnlyExecutionProjectionComponent.VALUATION, applied_ledger)
        self._authority = authority
        self._accounts = account_manager
        self._ledgers = ledger_manager

    def apply_execution_projection(self, context: OnlyExecutionProjectionApplyContext) -> OnlyProjectionApplyResult:
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
    settlement_manager: OnlySettlementManager,
    fee_manager: OnlyFeeManager,
    account_manager: OnlyAccountManager,
    ledger_manager: OnlyStrategyLedgerManager,
    risk_service: OnlyRiskService,
    valuation_authority: OnlyExecutionValuationAuthority,
    applied_ledger: OnlyAppliedProjectionLedger,
) -> Mapping[OnlyExecutionProjectionComponent, OnlyExecutionProjectionTarget]:
    targets: tuple[OnlyExecutionProjectionTarget, ...] = (
        OnlyOrderExecutionProjectionTarget(order_manager, applied_ledger),
        OnlyPositionExecutionProjectionTarget(position_manager, applied_ledger),
        OnlyAllocationExecutionProjectionTarget(allocation_manager, applied_ledger),
        OnlySettlementExecutionProjectionTarget(settlement_manager, applied_ledger),
        OnlyFeeExecutionProjectionTarget(fee_manager, applied_ledger),
        OnlyAccountExecutionProjectionTarget(account_manager, applied_ledger),
        OnlyStrategyLedgerExecutionProjectionTarget(ledger_manager, applied_ledger),
        OnlyAccountCashReservationExecutionProjectionTarget(account_manager, applied_ledger),
        OnlyStrategyCashReservationExecutionProjectionTarget(ledger_manager, applied_ledger),
        OnlyRiskReservationExecutionProjectionTarget(risk_service, applied_ledger),
        OnlyRiskExecutionProjectionTarget(risk_service, applied_ledger),
        OnlyValuationExecutionProjectionTarget(
            valuation_authority,
            account_manager,
            ledger_manager,
            applied_ledger,
        ),
    )
    result = {target.component: target for target in targets}
    if len(result) != 12:
        raise RuntimeError("Generic T0 Projection Target registry is incomplete or duplicated")
    return result


__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("only_")]
