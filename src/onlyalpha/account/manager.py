"""Runtime-owned single-writer local Account truth."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from decimal import Decimal

from onlyalpha.account.enums import (
    OnlyAccountCashChangeType,
    OnlyAccountMutationStatus,
    OnlyAccountReservationState,
    OnlyAccountStatus,
)
from onlyalpha.account.events import OnlyAccountEvent, OnlyAccountEventPublisher, OnlyNullAccountEventPublisher
from onlyalpha.account.identifiers import OnlyAccountReservationId
from onlyalpha.account.models import (
    OnlyAccountCashBalance,
    OnlyAccountCashChange,
    OnlyAccountConfig,
    OnlyAccountFee,
    OnlyAccountMutationResult,
    OnlyAccountReservation,
    OnlyAccountSnapshot,
    OnlyAccountTradeCashFlow,
    OnlyAccountValuation,
)
from onlyalpha.account.performance import OnlyAccountValuationSource
from onlyalpha.account.repositories import OnlyAccountRepository, OnlyInMemoryAccountRepository
from onlyalpha.account.reservations import OnlyAccountReservationManager
from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyRuntimeId, OnlyTradeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyMoney


@dataclass(slots=True)
class OnlyAccount:
    config: OnlyAccountConfig
    ledger_cash: OnlyMoney
    order_reserved_cash: OnlyMoney
    unsettled_receivable_cash: OnlyMoney
    position_market_value: OnlyMoney
    realized_pnl: OnlyMoney
    unrealized_pnl: OnlyMoney
    fees: OnlyMoney
    status: OnlyAccountStatus
    created_at: OnlyTimestamp
    updated_at: OnlyTimestamp
    valuation_time: OnlyTimestamp | None = None
    version: int = 1
    last_external_sequence: int | None = None
    quality_flags: tuple[str, ...] = ()
    reserved_margin: Decimal = Decimal(0)
    occupied_margin: Decimal = Decimal(0)
    released_margin: Decimal = Decimal(0)


class OnlyAccountManager:
    """Owns local cash-account state for exactly one Runtime."""

    def __init__(
        self,
        runtime_id: OnlyRuntimeId,
        *,
        repository: OnlyAccountRepository | None = None,
        publisher: OnlyAccountEventPublisher | None = None,
        reservation_manager: OnlyAccountReservationManager | None = None,
    ) -> None:
        self.runtime_id = runtime_id
        self._repository = repository or OnlyInMemoryAccountRepository()
        self._publisher = publisher or OnlyNullAccountEventPublisher()
        self._accounts: dict[OnlyAccountId, OnlyAccount] = {}
        if reservation_manager is not None and reservation_manager.runtime_id != runtime_id:
            raise ValueError("Account ReservationManager belongs to another Runtime")
        self._reservation_manager = reservation_manager or OnlyAccountReservationManager(runtime_id)
        self._cash_change_ids: set[object] = set()
        self._fee_ids: set[object] = set()
        self._trade_ids: set[object] = set()
        self._valuation_versions: dict[OnlyAccountId, int] = {}
        self._event_sequence = 0
        self._performance_observer: (
            Callable[[OnlyAccountSnapshot, OnlyAccountValuationSource, OnlyAccountSnapshot | None], None] | None
        ) = None

    def bind_performance_observer(
        self,
        observer: Callable[[OnlyAccountSnapshot, OnlyAccountValuationSource, OnlyAccountSnapshot | None], None],
    ) -> None:
        if self._accounts:
            raise ValueError("Account performance observer must bind before Account creation")
        self._performance_observer = observer

    def bind_publisher(self, publisher: OnlyAccountEventPublisher) -> None:
        if self._accounts:
            raise ValueError("Account publisher must bind before Account creation")
        self._publisher = publisher

    def create_account(self, config: OnlyAccountConfig, timestamp: OnlyTimestamp) -> OnlyAccountSnapshot:
        self._require_scope(config.runtime_id)
        existing = self._accounts.get(config.account_id)
        if existing is not None:
            return self._snapshot(existing)
        zero = OnlyMoney(Decimal(0), config.base_currency)
        state = OnlyAccount(
            config,
            config.initial_cash,
            zero,
            zero,
            zero,
            zero,
            zero,
            zero,
            OnlyAccountStatus.ACTIVE,
            timestamp,
            timestamp,
        )
        self._accounts[config.account_id] = state
        snapshot = self._save(state)
        self._observe(snapshot, OnlyAccountValuationSource.ACCOUNT_CREATED, None)
        self._publish("ACCOUNT_CREATED", snapshot, timestamp)
        return snapshot

    def apply_cash_change(self, change: OnlyAccountCashChange) -> OnlyAccountMutationResult:
        state = self._require(change.account_id)
        self._require_scope(change.runtime_id)
        before = self._snapshot(state)
        if change.change_id in self._cash_change_ids:
            return self._unchanged(before)
        amount = change.amount.amount
        if change.change_type in {OnlyAccountCashChangeType.WITHDRAWAL, OnlyAccountCashChangeType.FEE}:
            amount = -abs(amount)
        updated = state.ledger_cash.amount + amount
        if updated < 0:
            raise ValueError("Account cash cannot become negative")
        state.ledger_cash = OnlyMoney(updated, state.config.base_currency)
        self._cash_change_ids.add(change.change_id)
        source = (
            OnlyAccountValuationSource.FEE_ADJUSTMENT
            if change.change_type is OnlyAccountCashChangeType.FEE
            else OnlyAccountValuationSource.EXTERNAL_CASH_FLOW
        )
        return self._commit(state, before, change.timestamp, "ACCOUNT_CASH_CHANGED", source)

    def reserve_cash(self, reservation: OnlyAccountReservation) -> OnlyAccountMutationResult:
        state = self._require(reservation.account_id)
        self._require_scope(reservation.runtime_id)
        before = self._snapshot(state)
        existing = self._reservation_manager.get(reservation.reservation_id)
        if existing is not None:
            if existing != reservation:
                raise ValueError("Account Reservation ID reused with different content")
            return self._unchanged(before)
        if reservation.remaining_amount.amount > before.cash.trade_available_cash.amount:
            raise ValueError("insufficient local Account cash")
        self._reservation_manager.add(reservation)
        state.order_reserved_cash = state.order_reserved_cash + reservation.remaining_amount
        return self._commit(state, before, reservation.updated_at, "ACCOUNT_CASH_RESERVED")

    def consume_cash_reservation(
        self,
        reservation_id: OnlyAccountReservationId,
        amount: OnlyMoney,
        timestamp: OnlyTimestamp,
    ) -> OnlyAccountMutationResult:
        state, reservation = self._find_reservation(reservation_id)
        before = self._snapshot(state)
        consume = min(amount.amount, reservation.remaining_amount.amount)
        if consume == 0:
            return self._unchanged(before)
        consumed = OnlyMoney(reservation.consumed_amount.amount + consume, amount.currency)
        remaining = OnlyMoney(reservation.remaining_amount.amount - consume, amount.currency)
        reservation = OnlyAccountReservation(
            reservation.reservation_id,
            reservation.runtime_id,
            reservation.account_id,
            reservation.order_id,
            reservation.reserved_amount,
            consumed,
            remaining,
            (
                OnlyAccountReservationState.CONSUMED
                if remaining.amount == 0
                else OnlyAccountReservationState.PARTIALLY_CONSUMED
            ),
            reservation.created_at,
            timestamp,
            reservation.version + 1,
        )
        self._reservation_manager.update(reservation)
        state.order_reserved_cash = OnlyMoney(state.order_reserved_cash.amount - consume, amount.currency)
        return self._commit(state, before, timestamp, "ACCOUNT_RESERVATION_CONSUMED")

    def release_cash(
        self,
        reservation_id: OnlyAccountReservationId,
        timestamp: OnlyTimestamp,
    ) -> OnlyAccountMutationResult:
        state, reservation = self._find_reservation(reservation_id)
        before = self._snapshot(state)
        if reservation.state is OnlyAccountReservationState.RELEASED:
            return self._unchanged(before)
        state.order_reserved_cash = state.order_reserved_cash - reservation.remaining_amount
        self._reservation_manager.update(
            OnlyAccountReservation(
                reservation.reservation_id,
                reservation.runtime_id,
                reservation.account_id,
                reservation.order_id,
                reservation.reserved_amount,
                reservation.consumed_amount,
                OnlyMoney(Decimal(0), reservation.remaining_amount.currency),
                OnlyAccountReservationState.RELEASED,
                reservation.created_at,
                timestamp,
                reservation.version + 1,
            )
        )
        return self._commit(state, before, timestamp, "ACCOUNT_RESERVATION_RELEASED")

    def apply_fee(self, fee: OnlyAccountFee) -> OnlyAccountMutationResult:
        state = self._require(fee.account_id)
        self._require_scope(fee.runtime_id)
        before = self._snapshot(state)
        if fee.fee_id in self._fee_ids:
            return self._unchanged(before)
        if fee.amount.amount > before.cash.trade_available_cash.amount:
            raise ValueError("Account fee exceeds available cash")
        state.ledger_cash = state.ledger_cash - fee.amount
        state.fees = state.fees + fee.amount
        self._fee_ids.add(fee.fee_id)
        return self._commit(
            state,
            before,
            fee.timestamp,
            "ACCOUNT_FEE_APPLIED",
            OnlyAccountValuationSource.FEE_ADJUSTMENT,
        )

    def apply_trade_cash_flow(self, cash_flow: OnlyAccountTradeCashFlow) -> OnlyAccountMutationResult:
        state = self._require(cash_flow.account_id)
        self._require_scope(cash_flow.runtime_id)
        before = self._snapshot(state)
        if cash_flow.trade_id in self._trade_ids:
            return self._unchanged(before)
        if cash_flow.external_sequence < (state.last_external_sequence or -1):
            state.status = OnlyAccountStatus.RECONCILING
            state.quality_flags = tuple(sorted(set(state.quality_flags + ("STALE_TRADE",))))
            self._trade_ids.add(cash_flow.trade_id)
            return self._commit(state, before, cash_flow.timestamp, "ACCOUNT_RECONCILIATION_STARTED")
        if cash_flow.settle_notional:
            delta = (
                -(cash_flow.notional.amount + cash_flow.fee.amount)
                if cash_flow.side is OnlyOrderSide.BUY
                else cash_flow.notional.amount - cash_flow.fee.amount
            )
        else:
            delta = cash_flow.realized_pnl_delta.amount - cash_flow.fee.amount
        if state.ledger_cash.amount + delta < 0:
            raise ValueError("Account Trade would create negative cash")
        state.ledger_cash = OnlyMoney(state.ledger_cash.amount + delta, state.config.base_currency)
        state.fees = state.fees + cash_flow.fee
        state.realized_pnl = state.realized_pnl + cash_flow.realized_pnl_delta
        state.last_external_sequence = cash_flow.external_sequence
        self._trade_ids.add(cash_flow.trade_id)
        return self._commit(
            state,
            before,
            cash_flow.timestamp,
            "ACCOUNT_TRADE_APPLIED",
            OnlyAccountValuationSource.COMMITTED_EXECUTION,
        )

    def apply_margin_change(
        self,
        account_id: OnlyAccountId,
        *,
        reserved_delta: Decimal = Decimal(0),
        occupied_delta: Decimal = Decimal(0),
        released_delta: Decimal = Decimal(0),
        timestamp: OnlyTimestamp,
    ) -> OnlyAccountMutationResult:
        state = self._require(account_id)
        before = self._snapshot(state)
        quantum = Decimal(1).scaleb(-state.config.base_currency.precision)
        state.reserved_margin = (state.reserved_margin + reserved_delta).quantize(quantum)
        state.occupied_margin = (state.occupied_margin + occupied_delta).quantize(quantum)
        state.released_margin = (state.released_margin + released_delta).quantize(quantum)
        if min(state.reserved_margin, state.occupied_margin, state.released_margin) < 0:
            raise ValueError("Account margin cannot become negative")
        if state.reserved_margin + state.occupied_margin > state.ledger_cash.amount:
            raise ValueError("Account margin exceeds cash collateral")
        return self._commit(
            state,
            before,
            timestamp,
            "ACCOUNT_MARGIN_CHANGED",
            OnlyAccountValuationSource.MARGIN,
        )

    def apply_valuation(self, valuation: OnlyAccountValuation) -> OnlyAccountMutationResult:
        state = self._require(valuation.account_id)
        self._require_scope(valuation.runtime_id)
        before = self._snapshot(state)
        previous = self._valuation_versions.get(valuation.account_id)
        if previous is not None and valuation.valuation_version <= previous:
            return self._unchanged(before)
        state.position_market_value = valuation.position_market_value
        state.unrealized_pnl = valuation.unrealized_pnl
        state.valuation_time = valuation.timestamp
        self._valuation_versions[valuation.account_id] = valuation.valuation_version
        return self._commit(
            state,
            before,
            valuation.timestamp,
            "ACCOUNT_VALUED",
            OnlyAccountValuationSource.MARKET_VALUATION,
        )

    def start_reconciliation(
        self,
        account_id: OnlyAccountId,
        timestamp: OnlyTimestamp,
        quality_flag: str,
    ) -> OnlyAccountSnapshot:
        state = self._require(account_id)
        before = self._snapshot(state)
        state.status = OnlyAccountStatus.RECONCILING
        state.quality_flags = tuple(sorted(set(state.quality_flags + (quality_flag,))))
        return self._commit(state, before, timestamp, "ACCOUNT_RECONCILIATION_STARTED").after

    def clear_reconciliation(self, account_id: OnlyAccountId, timestamp: OnlyTimestamp) -> OnlyAccountSnapshot:
        state = self._require(account_id)
        before = self._snapshot(state)
        state.status = OnlyAccountStatus.ACTIVE
        state.quality_flags = ()
        return self._commit(state, before, timestamp, "ACCOUNT_RECONCILED").after

    def get_snapshot(self, account_id: OnlyAccountId) -> OnlyAccountSnapshot | None:
        state = self._accounts.get(account_id)
        return None if state is None else self._snapshot(state)

    def require_snapshot(self, account_id: OnlyAccountId) -> OnlyAccountSnapshot:
        snapshot = self.get_snapshot(account_id)
        if snapshot is None:
            raise KeyError(f"Account not found: {account_id}")
        return snapshot

    def list_accounts(self) -> tuple[OnlyAccountSnapshot, ...]:
        return tuple(self._snapshot(self._accounts[key]) for key in sorted(self._accounts, key=str))

    @property
    def execution_event_sequence(self) -> int:
        return self._event_sequence

    def restore_execution_event_sequence(self, sequence: int) -> None:
        if sequence < self._event_sequence:
            raise ValueError("Account event sequence cannot regress")
        self._event_sequence = sequence

    def get_cash_reservation(self, reservation_id: OnlyAccountReservationId) -> OnlyAccountReservation | None:
        return self._reservation_manager.get(reservation_id)

    def restore_cash_reservation_execution_authority(self, reservation: OnlyAccountReservation) -> None:
        self._reservation_manager.restore_execution_authority(reservation)
        state = self._require(reservation.account_id)
        self._repository.save(self._snapshot(state))

    def restore_valuation_version(self, account_id: OnlyAccountId, version: int) -> None:
        if version < 1:
            raise ValueError("Account valuation version must be positive")
        self._valuation_versions[account_id] = version

    def restore_execution_authority(
        self,
        snapshot: OnlyAccountSnapshot,
        *,
        trade_ids: tuple[object, ...] = (),
    ) -> None:
        self._require_scope(snapshot.runtime_id)
        state = self._require(snapshot.account_id)
        if state.config.gateway_id != snapshot.gateway_id or state.config.base_currency != snapshot.base_currency:
            raise ValueError("Account replay scope differs from registered Account")
        candidate = replace(
            state,
            ledger_cash=snapshot.cash.ledger_cash,
            order_reserved_cash=snapshot.cash.order_reserved_cash,
            unsettled_receivable_cash=snapshot.cash.unsettled_receivable_cash,
            position_market_value=snapshot.position_market_value,
            realized_pnl=snapshot.realized_pnl,
            unrealized_pnl=snapshot.unrealized_pnl,
            fees=snapshot.fees,
            status=snapshot.status,
            created_at=snapshot.created_at,
            updated_at=snapshot.updated_at,
            valuation_time=snapshot.valuation_time,
            version=snapshot.version,
            last_external_sequence=snapshot.last_external_sequence,
            quality_flags=snapshot.quality_flags,
            reserved_margin=Decimal(0) if snapshot.reserved_margin is None else snapshot.reserved_margin.amount,
            occupied_margin=Decimal(0) if snapshot.occupied_margin is None else snapshot.occupied_margin.amount,
            released_margin=Decimal(0) if snapshot.released_margin is None else snapshot.released_margin.amount,
        )
        restored = self._snapshot(candidate)
        if restored != snapshot:
            raise ValueError("restored Account does not reproduce committed Snapshot")
        installed_trade_ids = set(self._trade_ids)
        installed_trade_ids.update(trade_ids)
        self._repository.replace_execution_authority(restored)
        self._accounts[snapshot.account_id] = candidate
        self._trade_ids = installed_trade_ids

    def capture_checkpoint(self) -> object:
        """Return canonical, complete Account authority for a Runtime checkpoint."""

        return {
            "accounts": [item.to_json() for item in self.list_accounts()],
            "event_sequence": self._event_sequence,
            "trade_ids": sorted(str(item) for item in self._trade_ids),
            "valuation_versions": [
                [str(account_id), version]
                for account_id, version in sorted(self._valuation_versions.items(), key=lambda item: str(item[0]))
            ],
        }

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, dict):
            raise ValueError("Account checkpoint must be an object")
        snapshots = tuple(OnlyAccountSnapshot.from_json(str(item)) for item in payload["accounts"])
        trade_ids = tuple(OnlyTradeId(str(item)) for item in payload["trade_ids"])
        for snapshot in snapshots:
            for reservation in snapshot.reservations:
                self._reservation_manager.restore_execution_authority(reservation)
            self.restore_execution_authority(snapshot, trade_ids=trade_ids)
        for account_id, version in payload["valuation_versions"]:
            self.restore_valuation_version(OnlyAccountId(str(account_id)), int(version))
        self.restore_execution_event_sequence(int(payload["event_sequence"]))

    def _snapshot(self, state: OnlyAccount) -> OnlyAccountSnapshot:
        currency = state.config.base_currency
        trade_available = OnlyMoney(state.ledger_cash.amount - state.order_reserved_cash.amount, currency)
        withdrawable = OnlyMoney(trade_available.amount - state.unsettled_receivable_cash.amount, currency)
        cash = OnlyAccountCashBalance(
            state.ledger_cash,
            trade_available,
            withdrawable,
            state.order_reserved_cash,
            state.unsettled_receivable_cash,
        )
        return OnlyAccountSnapshot(
            state.config.runtime_id,
            state.config.account_id,
            state.config.gateway_id,
            state.config.account_type,
            currency,
            state.status,
            cash,
            state.position_market_value,
            state.realized_pnl,
            state.unrealized_pnl,
            state.fees,
            state.ledger_cash + state.position_market_value,
            self._reservation_manager.list_by_account(state.config.account_id),
            state.created_at,
            state.updated_at,
            state.valuation_time,
            state.version,
            state.last_external_sequence,
            state.quality_flags,
            reserved_margin=OnlyMoney(state.reserved_margin, currency),
            occupied_margin=OnlyMoney(state.occupied_margin, currency),
            released_margin=OnlyMoney(state.released_margin, currency),
            available_margin=OnlyMoney(
                withdrawable.amount - state.reserved_margin - state.occupied_margin,
                currency,
            ),
        )

    def _commit(
        self,
        state: OnlyAccount,
        before: OnlyAccountSnapshot,
        timestamp: OnlyTimestamp,
        event_type: str,
        source: OnlyAccountValuationSource = OnlyAccountValuationSource.STATE_CHANGE,
    ) -> OnlyAccountMutationResult:
        state.updated_at = timestamp
        state.version += 1
        after = self._save(state)
        self._observe(after, source, before)
        self._publish(event_type, after, timestamp)
        return OnlyAccountMutationResult(OnlyAccountMutationStatus.APPLIED, before, after, True)

    def _observe(
        self,
        snapshot: OnlyAccountSnapshot,
        source: OnlyAccountValuationSource,
        previous: OnlyAccountSnapshot | None,
    ) -> None:
        if self._performance_observer is not None:
            self._performance_observer(snapshot, source, previous)

    def _save(self, state: OnlyAccount) -> OnlyAccountSnapshot:
        snapshot = self._snapshot(state)
        self._repository.save(snapshot)
        return snapshot

    def _publish(self, event_type: str, snapshot: OnlyAccountSnapshot, timestamp: OnlyTimestamp) -> None:
        self._event_sequence += 1
        self._publisher.publish(OnlyAccountEvent(event_type, snapshot, timestamp, self._event_sequence))

    def _require(self, account_id: OnlyAccountId) -> OnlyAccount:
        try:
            return self._accounts[account_id]
        except KeyError as exc:
            raise KeyError(f"Account not found: {account_id}") from exc

    def _find_reservation(
        self,
        reservation_id: OnlyAccountReservationId,
    ) -> tuple[OnlyAccount, OnlyAccountReservation]:
        reservation = self._reservation_manager.require(reservation_id)
        return self._require(reservation.account_id), reservation

    def _require_scope(self, runtime_id: OnlyRuntimeId) -> None:
        if runtime_id != self.runtime_id:
            raise ValueError("Account input belongs to another Runtime")

    @staticmethod
    def _unchanged(snapshot: OnlyAccountSnapshot) -> OnlyAccountMutationResult:
        return OnlyAccountMutationResult(OnlyAccountMutationStatus.DUPLICATE, snapshot, snapshot, False)
