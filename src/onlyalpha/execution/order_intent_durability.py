"""Runtime-owned implementation of the durable Order Intent barrier."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from onlyalpha.account.identifiers import OnlyAccountReservationId
from onlyalpha.account.manager import OnlyAccountManager
from onlyalpha.account.models import OnlyAccountSnapshot
from onlyalpha.domain.execution import OnlyOrderRequest, OnlyOrderSnapshot
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency
from onlyalpha.margin.manager import OnlyMarginManager
from onlyalpha.order.intent import (
    OnlyOrderIntentDurabilityResult,
    OnlyRuntimeIntentReference,
)
from onlyalpha.position.allocation_manager import OnlyPositionAllocationManager
from onlyalpha.position.manager import OnlyPositionManager
from onlyalpha.position.models import OnlyPositionAllocationSnapshot, OnlyPositionSnapshot
from onlyalpha.position.reservations import OnlyPositionReservationManager
from onlyalpha.risk.service import OnlyRiskService
from onlyalpha.risk.snapshots import OnlyRiskSnapshot
from onlyalpha.strategy_ledger.locator import OnlyStrategyLedgerLocator
from onlyalpha.strategy_ledger.manager import OnlyStrategyLedgerManager
from onlyalpha.strategy_ledger.models import OnlyStrategyLedgerSnapshot
from onlyalpha.transaction.coordinator import (
    OnlyRuntimeTransactionCoordinationStatus,
    OnlyRuntimeTransactionCoordinator,
)

from .causal_recovery import (
    OnlyExecutionRecoveryDecisionKind,
    OnlyExecutionRecoveryResolution,
    OnlyExecutionRecoverySession,
)
from .execution_state import (
    only_account_cash_reservation_execution_state,
    only_account_execution_state,
    only_allocation_execution_state,
    only_margin_reservation_execution_state,
    only_order_execution_state,
    only_position_execution_state,
    only_position_reservation_execution_state,
    only_risk_execution_state,
    only_risk_reservation_execution_state,
    only_strategy_cash_reservation_execution_state,
    only_strategy_ledger_execution_state,
)
from .order_intent import (
    OnlyOrderIntentAllocationChange,
    OnlyOrderIntentPlanningContext,
    OnlyOrderIntentPositionChange,
    OnlyOrderIntentRuntimeTransactionPlanner,
)


@dataclass(frozen=True, slots=True)
class _OnlyOrderIntentCapture:
    request: OnlyOrderRequest
    cluster_id: OnlyClusterId
    account_id: OnlyAccountId
    prepared_at: OnlyTimestamp
    account_before: OnlyAccountSnapshot
    strategy_before: OnlyStrategyLedgerSnapshot
    positions_before: tuple[OnlyPositionSnapshot, ...]
    allocations_before: tuple[OnlyPositionAllocationSnapshot, ...]
    risk_before: OnlyRiskSnapshot


class OnlyRuntimeOrderIntentDurabilityService:
    """Capture local authority deltas and seal them through one Runtime transaction."""

    def __init__(
        self,
        *,
        accounts: OnlyAccountManager,
        ledgers: OnlyStrategyLedgerManager,
        ledger_locator: OnlyStrategyLedgerLocator,
        strategy_currency: OnlyCurrency,
        positions: OnlyPositionManager,
        allocations: OnlyPositionAllocationManager,
        position_reservations: OnlyPositionReservationManager,
        margins: OnlyMarginManager,
        risk: OnlyRiskService,
        coordinator: OnlyRuntimeTransactionCoordinator,
        now: Callable[[], OnlyTimestamp],
        on_ready: Callable[[object], None] | None = None,
        recovery_session: Callable[[], OnlyExecutionRecoverySession | None] | None = None,
    ) -> None:
        self._accounts = accounts
        self._ledgers = ledgers
        self._ledger_locator = ledger_locator
        self._strategy_currency = strategy_currency
        self._positions = positions
        self._allocations = allocations
        self._position_reservations = position_reservations
        self._margins = margins
        self._risk = risk
        self._coordinator = coordinator
        self._now = now
        self._planner = OnlyOrderIntentRuntimeTransactionPlanner()
        self._on_ready = on_ready
        self._recovery_session = recovery_session

    def begin(
        self,
        request: OnlyOrderRequest,
        cluster_id: OnlyClusterId,
        account_id: OnlyAccountId,
        prepared_at: OnlyTimestamp,
    ) -> object:
        recovery = None if self._recovery_session is None else self._recovery_session()
        if recovery is None and not self._coordinator.tail_is_projection_ready(self._risk.runtime_id):
            raise RuntimeError("ORDER_INTENT_PREVIOUS_TRANSACTION_NOT_PROJECTION_READY")
        return _OnlyOrderIntentCapture(
            request,
            cluster_id,
            account_id,
            prepared_at,
            self._accounts.require_snapshot(account_id),
            self._ledger_locator.require_snapshot(
                runtime_id=self._risk.runtime_id,
                account_id=account_id,
                cluster_id=cluster_id,
                currency=self._strategy_currency,
            ),
            self._positions.snapshot_all(),
            self._allocations.snapshot_all(),
            self._risk.get_snapshot(cluster_id),
        )

    def commit(self, token: object, order: OnlyOrderSnapshot) -> OnlyOrderIntentDurabilityResult:
        if not isinstance(token, _OnlyOrderIntentCapture):
            return OnlyOrderIntentDurabilityResult(False, None, "ORDER_INTENT_CAPTURE_INVALID")
        if (
            order.request_id != token.request.request_id
            or order.cluster_id != token.cluster_id
            or order.account_id != token.account_id
        ):
            return OnlyOrderIntentDurabilityResult(False, None, "ORDER_INTENT_CAPTURE_SCOPE_CONFLICT")
        try:
            prepared = self._planner.prepare(self._context(token, order))
            timestamp = self._now()
            session = None if self._recovery_session is None else self._recovery_session()
            decision = None if session is None else session.decide_autonomous(prepared)
            if decision is None or decision.kind is OnlyExecutionRecoveryDecisionKind.COMMIT_CONTINUATION:
                result = self._coordinator.commit(prepared, committed_at=timestamp, projected_at=timestamp)
            elif decision.kind is OnlyExecutionRecoveryDecisionKind.REHYDRATE_READY:
                assert decision.entry is not None
                result = self._coordinator.rehydrate_existing(
                    decision.entry.stored.committed,
                    projected_at=timestamp,
                )
            else:
                assert decision.entry is not None
                result = self._coordinator.recover_existing(
                    decision.entry.stored.committed,
                    projected_at=timestamp,
                )
        except (AssertionError, KeyError, RuntimeError, TypeError, ValueError) as exc:
            return OnlyOrderIntentDurabilityResult(False, None, f"{type(exc).__name__}: {exc}")
        if result.status not in {
            OnlyRuntimeTransactionCoordinationStatus.COMMITTED_AND_PROJECTED,
            OnlyRuntimeTransactionCoordinationStatus.ALREADY_READY,
        }:
            return OnlyOrderIntentDurabilityResult(False, None, result.error or result.status.value)
        transaction = result.transaction
        if transaction is None:
            return OnlyOrderIntentDurabilityResult(False, None, "ORDER_INTENT_COMMITTED_TRANSACTION_MISSING")
        if session is not None and decision is not None:
            if decision.kind is OnlyExecutionRecoveryDecisionKind.COMMIT_CONTINUATION:
                session.record_autonomous_continuation(transaction)
            else:
                session.resolve_persisted(
                    transaction.execution_sequence,
                    OnlyExecutionRecoveryResolution.READY_REHYDRATED
                    if decision.kind is OnlyExecutionRecoveryDecisionKind.REHYDRATE_READY
                    else OnlyExecutionRecoveryResolution.UNPROJECTED_RECOVERED,
                )
        elif self._on_ready is not None:
            self._on_ready(transaction)
        return OnlyOrderIntentDurabilityResult(
            True,
            OnlyRuntimeIntentReference(transaction.transaction_id, transaction.prepared_authority_hash),
        )

    def _context(self, capture: _OnlyOrderIntentCapture, order: OnlyOrderSnapshot) -> OnlyOrderIntentPlanningContext:
        positions_before = {item.position_id: item for item in capture.positions_before}
        positions_after = {item.position_id: item for item in self._positions.snapshot_all()}
        position_changes = tuple(
            OnlyOrderIntentPositionChange(
                only_position_execution_state(before),
                only_position_execution_state(positions_after[position_id]),
                self._positions.creation_cycle_head(before.key),
            )
            for position_id, before in sorted(positions_before.items(), key=lambda item: str(item[0]))
            if positions_after.get(position_id) != before
        )
        allocations_before = {item.allocation_id: item for item in capture.allocations_before}
        allocations_after = {item.allocation_id: item for item in self._allocations.snapshot_all()}
        allocation_changes = tuple(
            OnlyOrderIntentAllocationChange(
                only_allocation_execution_state(before),
                only_allocation_execution_state(allocations_after[allocation_id]),
                self._allocations.creation_cycle_head(before.key),
            )
            for allocation_id, before in sorted(allocations_before.items(), key=lambda item: str(item[0]))
            if allocations_after.get(allocation_id) != before
        )
        account_after = self._accounts.require_snapshot(order.account_id)
        strategy_after = self._ledgers.require_snapshot(capture.strategy_before.key)
        account_reservation = self._accounts.get_cash_reservation(
            OnlyAccountReservationId(f"ARESV-{order.runtime_id}-{order.order_id}")
        )
        strategy_reservation = self._ledgers.get_cash_reservation(capture.strategy_before.key, order.order_id)
        position_reservation = self._position_reservations.get(order.order_id)
        margin_reservation = self._margins.get(str(order.order_id))
        risk_reservation = self._risk.reservations.get_for_order(order.order_id)
        risk_after = self._risk.get_snapshot(order.cluster_id)
        return OnlyOrderIntentPlanningContext(
            order_after=only_order_execution_state(order),
            prepared_at=max(capture.prepared_at, order.created_at),
            account_before=only_account_execution_state(capture.account_before),
            account_after=only_account_execution_state(account_after),
            strategy_ledger_before=only_strategy_ledger_execution_state(capture.strategy_before),
            strategy_ledger_after=only_strategy_ledger_execution_state(strategy_after),
            position_changes=position_changes,
            allocation_changes=allocation_changes,
            account_cash_reservation_after=(
                None
                if account_reservation is None
                else only_account_cash_reservation_execution_state(account_reservation)
            ),
            strategy_cash_reservation_after=(
                None
                if strategy_reservation is None
                else only_strategy_cash_reservation_execution_state(strategy_reservation)
            ),
            position_reservation_after=(
                None
                if position_reservation is None
                else only_position_reservation_execution_state(position_reservation)
            ),
            margin_reservation_after=(
                None if margin_reservation is None else only_margin_reservation_execution_state(margin_reservation)
            ),
            risk_reservation_after=(
                None if risk_reservation is None else only_risk_reservation_execution_state(risk_reservation)
            ),
            risk_before=only_risk_execution_state(capture.risk_before),
            risk_after=only_risk_execution_state(risk_after),
        )


__all__ = ["OnlyRuntimeOrderIntentDurabilityService"]
