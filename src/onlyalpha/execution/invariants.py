"""Cross-component invariant checks executed before facts are committed."""

from decimal import Decimal

from onlyalpha.account.manager import OnlyAccountManager
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyInstrumentId
from onlyalpha.position.allocation_manager import OnlyPositionAllocationManager
from onlyalpha.position.manager import OnlyPositionManager
from onlyalpha.position.reservations import OnlyPositionReservationManager
from onlyalpha.risk.service import OnlyRiskService
from onlyalpha.strategy_ledger.manager import OnlyStrategyLedgerManager

from .models import OnlyExecutionInvariantResult, OnlyExecutionInvariantViolation


class OnlyExecutionInvariantChecker:
    def __init__(
        self,
        positions: OnlyPositionManager,
        allocations: OnlyPositionAllocationManager,
        ledgers: OnlyStrategyLedgerManager,
        accounts: OnlyAccountManager,
        position_reservations: OnlyPositionReservationManager,
        risk: OnlyRiskService,
    ) -> None:
        self._positions = positions
        self._allocations = allocations
        self._ledgers = ledgers
        self._accounts = accounts
        self._position_reservations = position_reservations
        self._risk = risk

    def check(self, account_id: OnlyAccountId, instrument_id: OnlyInstrumentId) -> OnlyExecutionInvariantResult:
        violations: list[OnlyExecutionInvariantViolation] = []
        account_positions = self._positions.list_by_account(account_id)
        account_quantity = sum(
            (item.total_quantity.value for item in account_positions if item.key.instrument_id == instrument_id),
            Decimal(0),
        )
        allocation_quantity = sum(
            (
                item.total_quantity.value
                for item in self._allocations.list_by_account(account_id)
                if item.key.instrument_id == instrument_id
            ),
            Decimal(0),
        )
        unallocated_quantity = sum(
            (
                item.total_quantity.value
                for item in self._allocations.unallocated()
                if item.instrument_id == instrument_id
            ),
            Decimal(0),
        )
        if account_quantity != allocation_quantity + unallocated_quantity:
            violations.append(
                OnlyExecutionInvariantViolation(
                    "POSITION_ALLOCATION_MISMATCH",
                    f"account={account_quantity} allocation={allocation_quantity} unallocated={unallocated_quantity}",
                )
            )
        for position in account_positions:
            if position.total_quantity.value < 0 or position.available_quantity.value < 0:
                violations.append(OnlyExecutionInvariantViolation("NEGATIVE_POSITION", str(position.key)))
            if (
                position.unsettled_quantity.value > 0
                and position.available_quantity.value > position.settled_quantity.value
            ):
                violations.append(OnlyExecutionInvariantViolation("T1_AVAILABILITY", str(position.key)))
        for allocation in self._allocations.list_by_account(account_id):
            if allocation.total_quantity.value < 0:
                violations.append(OnlyExecutionInvariantViolation("NEGATIVE_ALLOCATION", str(allocation.key)))
        for ledger in self._ledgers.list_ledgers():
            if (
                ledger.key.account_id == account_id
                and ledger.equity.equity_by_cash_view != ledger.equity.equity_by_pnl_view
            ):
                violations.append(OnlyExecutionInvariantViolation("LEDGER_EQUITY_VIEW_MISMATCH", str(ledger.key)))
        account = self._accounts.require_snapshot(account_id)
        if account.equity.amount != account.cash.cash_balance.amount + account.position_market_value.amount:
            violations.append(OnlyExecutionInvariantViolation("ACCOUNT_EQUITY_MISMATCH", str(account_id)))
        for reservation in account.reservations:
            if (
                min(
                    reservation.reserved_amount.amount,
                    reservation.consumed_amount.amount,
                    reservation.remaining_amount.amount,
                )
                < 0
            ):
                violations.append(
                    OnlyExecutionInvariantViolation("NEGATIVE_ACCOUNT_RESERVATION", str(reservation.reservation_id))
                )
        for risk_reservation in self._risk.reservations.snapshot_all():
            if risk_reservation.reserved_quantity.value < 0:
                violations.append(
                    OnlyExecutionInvariantViolation(
                        "NEGATIVE_RISK_RESERVATION",
                        str(risk_reservation.reservation_id),
                    )
                )
        position_reservation = self._position_reservations.active_quantity(instrument_id, account_id=account_id)
        if position_reservation.value < 0:
            violations.append(OnlyExecutionInvariantViolation("NEGATIVE_POSITION_RESERVATION", str(instrument_id)))
        return OnlyExecutionInvariantResult(not violations, tuple(violations))
