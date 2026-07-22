"""Runtime-owned single-writer Strategy Ledger manager."""

from decimal import ROUND_HALF_EVEN, Decimal

from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyOrderId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.strategy_ledger.entities import OnlyStrategyLedger
from onlyalpha.strategy_ledger.enums import (
    OnlyStrategyCashEntryType,
    OnlyStrategyCashReservationStage,
    OnlyStrategyLedgerMutationStatus,
    OnlyStrategyLedgerStatus,
)
from onlyalpha.strategy_ledger.exceptions import (
    OnlyStrategyLedgerInsufficientCashError,
    OnlyStrategyLedgerScopeError,
)
from onlyalpha.strategy_ledger.identifiers import (
    OnlyStrategyCashFlowId,
    OnlyStrategyFeeEntryId,
    OnlyStrategyLedgerId,
)
from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey
from onlyalpha.strategy_ledger.models import (
    OnlyStrategyFeeEntry,
    OnlyStrategyLedgerEquityPoint,
    OnlyStrategyLedgerEvent,
    OnlyStrategyLedgerMutationResult,
    OnlyStrategyLedgerSnapshot,
    OnlyStrategyTradeAccountingInput,
    OnlyStrategyValuation,
    only_zero_money,
)
from onlyalpha.strategy_ledger.ports import (
    OnlyStrategyLedgerEventPublisher,
    OnlyStrategyLedgerRepository,
)
from onlyalpha.strategy_ledger.publisher import OnlyNoOpStrategyLedgerEventPublisher
from onlyalpha.strategy_ledger.repositories import OnlyInMemoryStrategyLedgerRepository
from onlyalpha.strategy_ledger.reservations import OnlyStrategyCashReservationManager


class OnlyStrategyLedgerManager:
    """Owns all virtual Cluster ledgers inside exactly one Runtime."""

    def __init__(
        self,
        runtime_id: OnlyRuntimeId,
        *,
        repository: OnlyStrategyLedgerRepository | None = None,
        publisher: OnlyStrategyLedgerEventPublisher | None = None,
    ) -> None:
        self.runtime_id = runtime_id
        self._repository = repository or OnlyInMemoryStrategyLedgerRepository()
        self._publisher = publisher or OnlyNoOpStrategyLedgerEventPublisher()
        self._ledgers: dict[OnlyStrategyLedgerKey, OnlyStrategyLedger] = {}
        self._scope_index: dict[
            tuple[OnlyRuntimeId, OnlyAccountId, OnlyClusterId, OnlyCurrency],
            OnlyStrategyLedgerKey,
        ] = {}
        self._reservations: dict[OnlyStrategyLedgerKey, OnlyStrategyCashReservationManager] = {}
        self._trade_fingerprints: set[str] = set()
        self._fee_ids: set[OnlyStrategyFeeEntryId] = set()
        self._cash_flow_ids: set[OnlyStrategyCashFlowId] = set()
        self._valuation_versions: dict[OnlyStrategyLedgerKey, int] = {}
        self._event_sequence = 0
        self._equity_sequence = 0
        self._equity_timelines: dict[OnlyStrategyLedgerKey, list[OnlyStrategyLedgerEquityPoint]] = {}

    def create_ledger(
        self,
        key: OnlyStrategyLedgerKey,
        initial_capital: OnlyMoney,
        timestamp: OnlyTimestamp,
    ) -> OnlyStrategyLedgerSnapshot:
        self._require_scope(key)
        scope = (key.runtime_id, key.account_id, key.cluster_id, key.base_currency)
        if scope in self._scope_index:
            raise ValueError(f"Strategy Ledger scope already registered: {key}")
        ledger_id = OnlyStrategyLedgerId(
            f"SLEDGER-{key.runtime_id}-{key.account_id}-{key.cluster_id}-{key.base_currency.code}"
        )
        ledger = OnlyStrategyLedger(ledger_id, key, initial_capital, timestamp)
        self._ledgers[key] = ledger
        self._scope_index[scope] = key
        self._reservations[key] = OnlyStrategyCashReservationManager(key)
        snapshot = self._save(ledger)
        self._publish("STRATEGY_LEDGER_CREATED", snapshot, timestamp)
        return snapshot

    def bind_publisher(self, publisher: OnlyStrategyLedgerEventPublisher) -> None:
        """Bind the Runtime adapter before any Ledger is registered."""

        if self._ledgers:
            raise ValueError("Strategy Ledger publisher must bind before Ledger creation")
        self._publisher = publisher

    def activate_ledger(self, key: OnlyStrategyLedgerKey, timestamp: OnlyTimestamp) -> OnlyStrategyLedgerSnapshot:
        ledger = self._require_entity(key)
        if ledger.activate(timestamp):
            snapshot = self._save(ledger)
            self._publish("STRATEGY_LEDGER_ACTIVATED", snapshot, timestamp)
            return snapshot
        return self._snapshot(ledger)

    def close_ledger(self, key: OnlyStrategyLedgerKey, timestamp: OnlyTimestamp) -> OnlyStrategyLedgerSnapshot:
        ledger = self._require_entity(key)
        if ledger.close(timestamp):
            snapshot = self._save(ledger)
            self._publish("STRATEGY_LEDGER_CLOSED", snapshot, timestamp)
            return snapshot
        return self._snapshot(ledger)

    def reserve_cash(
        self,
        key: OnlyStrategyLedgerKey,
        order_id: OnlyOrderId,
        estimated_notional: OnlyMoney,
        estimated_fee: OnlyMoney,
        timestamp: OnlyTimestamp,
    ) -> OnlyStrategyLedgerMutationResult:
        ledger = self._require_entity(key)
        before = self._snapshot(ledger)
        requested = estimated_notional + estimated_fee
        if requested.amount > before.cash.cash_available.amount:
            raise OnlyStrategyLedgerInsufficientCashError("insufficient Strategy cash available")
        reservation, changed = self._reservations[key].create(order_id, estimated_notional, estimated_fee, timestamp)
        if not changed:
            return self._unchanged(before, OnlyStrategyLedgerMutationStatus.DUPLICATE)
        ledger.record_reservation(
            reservation,
            OnlyStrategyCashEntryType.ORDER_RESERVATION,
            OnlyMoney(-requested.amount, key.base_currency),
            timestamp,
        )
        after = self._save(ledger)
        event = self._publish("STRATEGY_CASH_RESERVED", after, timestamp)
        return self._result(before, after, (event,))

    def advance_cash_reservation(
        self,
        key: OnlyStrategyLedgerKey,
        order_id: OnlyOrderId,
        stage: OnlyStrategyCashReservationStage,
        timestamp: OnlyTimestamp,
    ) -> OnlyStrategyLedgerSnapshot:
        ledger = self._require_entity(key)
        _, changed = self._reservations[key].advance_stage(order_id, stage, timestamp)
        if changed:
            ledger.reservation_changed(timestamp)
            return self._save(ledger)
        return self._snapshot(ledger)

    def release_cash_reservation(
        self, key: OnlyStrategyLedgerKey, order_id: OnlyOrderId, timestamp: OnlyTimestamp
    ) -> OnlyStrategyLedgerMutationResult:
        ledger = self._require_entity(key)
        before = self._snapshot(ledger)
        previous = self._reservations[key].require(order_id)
        reservation, changed = self._reservations[key].release(order_id, timestamp)
        if not changed:
            return self._unchanged(before, OnlyStrategyLedgerMutationStatus.DUPLICATE)
        ledger.record_reservation(
            reservation,
            OnlyStrategyCashEntryType.ORDER_RESERVATION_RELEASE,
            previous.remaining_amount,
            timestamp,
        )
        after = self._save(ledger)
        event = self._publish("STRATEGY_CASH_RESERVATION_RELEASED", after, timestamp)
        return self._result(before, after, (event,))

    def consume_cash_reservation(
        self,
        key: OnlyStrategyLedgerKey,
        order_id: OnlyOrderId,
        actual_amount: OnlyMoney,
        timestamp: OnlyTimestamp,
    ) -> OnlyStrategyLedgerSnapshot:
        ledger = self._require_entity(key)
        before = self._snapshot(ledger)
        reservation = self._reservations[key].require(order_id)
        extra = max(actual_amount.amount - reservation.remaining_amount.amount, Decimal(0))
        if extra > before.cash.cash_available.amount:
            raise OnlyStrategyLedgerInsufficientCashError("fill exceeds Reservation and available cash")
        _, changed = self._reservations[key].consume(order_id, actual_amount, timestamp, allow_extra=True)
        if changed:
            ledger.reservation_changed(timestamp)
            snapshot = self._save(ledger)
            self._publish("STRATEGY_CASH_RESERVATION_CONSUMED", snapshot, timestamp)
            return snapshot
        return before

    def apply_trade_accounting(
        self,
        key: OnlyStrategyLedgerKey,
        accounting: OnlyStrategyTradeAccountingInput,
        *,
        consume_cash_reservation: bool = True,
    ) -> OnlyStrategyLedgerMutationResult:
        ledger = self._require_entity(key)
        before = self._snapshot(ledger)
        fingerprints = self._fingerprints(accounting)
        if not fingerprints.isdisjoint(self._trade_fingerprints):
            return self._unchanged(before, OnlyStrategyLedgerMutationStatus.DUPLICATE)
        if ledger.last_trade_order is not None and accounting.stable_order < ledger.last_trade_order:
            ledger.status = OnlyStrategyLedgerStatus.RECONCILING
            ledger.quality_flags = tuple(sorted(set(ledger.quality_flags + ("STALE_TRADE",))))
            ledger.updated_at = accounting.ts_event
            ledger.version += 1
            after = self._save(ledger)
            self._publish("STRATEGY_LEDGER_RECONCILIATION_STARTED", after, accounting.ts_event)
            return OnlyStrategyLedgerMutationResult(
                OnlyStrategyLedgerMutationStatus.STALE,
                before,
                after,
                only_zero_money(key.base_currency),
                only_zero_money(key.base_currency),
                only_zero_money(key.base_currency),
                (),
                "stale Trade requires deterministic replay",
            )
        if accounting.trade.opens_position and accounting.trade.side is OnlyOrderSide.BUY:
            reservation = self._reservations[key].require(accounting.trade.order_id)
            if (
                accounting.cash_reservation is None
                or accounting.cash_reservation.reservation_id != reservation.reservation_id
            ):
                raise ValueError("BUY accounting requires its Strategy Cash Reservation")
            if consume_cash_reservation:
                actual = self._trade_notional(key, accounting) + accounting.trade.fee
                self.consume_cash_reservation(key, accounting.trade.order_id, actual, accounting.ts_event)
        cash_delta, realized_delta, fee_delta = ledger.apply_trade(accounting)
        self._trade_fingerprints.update(fingerprints)
        self._fee_ids.update(entry.entry_id for entry in accounting.fee_entries)
        after = self._save(ledger)
        event = self._publish("STRATEGY_TRADE_APPLIED", after, accounting.ts_event)
        return OnlyStrategyLedgerMutationResult(
            OnlyStrategyLedgerMutationStatus.APPLIED,
            before,
            after,
            cash_delta,
            realized_delta,
            fee_delta,
            (event,),
        )

    def apply_fee(self, key: OnlyStrategyLedgerKey, entry: OnlyStrategyFeeEntry) -> OnlyStrategyLedgerMutationResult:
        ledger = self._require_entity(key)
        before = self._snapshot(ledger)
        if entry.key != key:
            raise OnlyStrategyLedgerScopeError("Fee belongs to another Ledger")
        if entry.entry_id in self._fee_ids:
            return self._unchanged(before, OnlyStrategyLedgerMutationStatus.DUPLICATE)
        ledger.apply_fee(entry)
        self._fee_ids.add(entry.entry_id)
        after = self._save(ledger)
        event = self._publish("STRATEGY_FEE_APPLIED", after, entry.ts_event)
        return self._result(before, after, (event,), fee_delta=entry.amount)

    def apply_external_cash_flow(
        self,
        key: OnlyStrategyLedgerKey,
        cash_flow_id: OnlyStrategyCashFlowId,
        amount: OnlyMoney,
        timestamp: OnlyTimestamp,
    ) -> OnlyStrategyLedgerMutationResult:
        ledger = self._require_entity(key)
        before = self._snapshot(ledger)
        if cash_flow_id in self._cash_flow_ids:
            return self._unchanged(before, OnlyStrategyLedgerMutationStatus.DUPLICATE)
        ledger.apply_external_cash_flow(cash_flow_id, amount, timestamp)
        self._cash_flow_ids.add(cash_flow_id)
        after = self._save(ledger)
        event = self._publish("STRATEGY_CASH_FLOW_APPLIED", after, timestamp)
        return self._result(before, after, (event,), cash_delta=amount)

    def apply_valuation(
        self,
        valuation: OnlyStrategyValuation,
        trading_day: OnlyTradingDay | None = None,
    ) -> OnlyStrategyLedgerMutationResult:
        ledger = self._require_entity(valuation.key)
        before = self._snapshot(ledger)
        previous = self._valuation_versions.get(valuation.key)
        if previous is not None and valuation.valuation_version == previous:
            return self._unchanged(before, OnlyStrategyLedgerMutationStatus.DUPLICATE)
        if previous is not None and valuation.valuation_version < previous:
            return self._unchanged(before, OnlyStrategyLedgerMutationStatus.STALE)
        ledger.apply_valuation(valuation, trading_day)
        self._valuation_versions[valuation.key] = valuation.valuation_version
        after = self._save(ledger)
        event = self._publish("STRATEGY_VALUATION_UPDATED", after, valuation.ts_event)
        return self._result(before, after, (event,))

    def get_snapshot(self, key: OnlyStrategyLedgerKey) -> OnlyStrategyLedgerSnapshot | None:
        self._require_scope(key)
        ledger = self._ledgers.get(key)
        return None if ledger is None else self._snapshot(ledger)

    def require_snapshot(self, key: OnlyStrategyLedgerKey) -> OnlyStrategyLedgerSnapshot:
        return self._snapshot(self._require_entity(key))

    def require_key(
        self,
        *,
        runtime_id: OnlyRuntimeId,
        account_id: OnlyAccountId,
        cluster_id: OnlyClusterId,
        currency: OnlyCurrency,
    ) -> OnlyStrategyLedgerKey:
        self._require_scope(OnlyStrategyLedgerKey(runtime_id, account_id, cluster_id, currency))
        scope = (runtime_id, account_id, cluster_id, currency)
        try:
            return self._scope_index[scope]
        except KeyError as exc:
            raise KeyError("Strategy Ledger not found for complete Runtime/Account/Cluster/Currency scope") from exc

    def require_snapshot_by_scope(
        self,
        *,
        runtime_id: OnlyRuntimeId,
        account_id: OnlyAccountId,
        cluster_id: OnlyClusterId,
        currency: OnlyCurrency,
    ) -> OnlyStrategyLedgerSnapshot:
        return self.require_snapshot(
            self.require_key(
                runtime_id=runtime_id,
                account_id=account_id,
                cluster_id=cluster_id,
                currency=currency,
            )
        )

    def list_ledgers(self) -> tuple[OnlyStrategyLedgerSnapshot, ...]:
        return tuple(
            sorted((self._snapshot(item) for item in self._ledgers.values()), key=lambda item: item.key.to_json())
        )

    def list_active_ledgers(self) -> tuple[OnlyStrategyLedgerSnapshot, ...]:
        return tuple(item for item in self.list_ledgers() if item.status.value == "ACTIVE")

    def equity_timeline(self, key: OnlyStrategyLedgerKey) -> tuple[OnlyStrategyLedgerEquityPoint, ...]:
        self._require_entity(key)
        return tuple(self._equity_timelines.get(key, ()))

    def valuation_count(self, key: OnlyStrategyLedgerKey) -> int:
        self._require_entity(key)
        return self._valuation_versions.get(key, 0)

    def _snapshot(self, ledger: OnlyStrategyLedger) -> OnlyStrategyLedgerSnapshot:
        reservations = self._reservations[ledger.key]
        return ledger.snapshot(reservations.active_reserved(), reservations.snapshots())

    def _save(self, ledger: OnlyStrategyLedger) -> OnlyStrategyLedgerSnapshot:
        snapshot = self._snapshot(ledger)
        self._repository.save(snapshot)
        self._repository.save_cash_entries(snapshot.cash_entries)
        self._repository.save_fee_entries(snapshot.fee_entries)
        self._repository.save_reservations(snapshot.reservations)
        self._equity_sequence += 1
        self._equity_timelines.setdefault(snapshot.key, []).append(
            OnlyStrategyLedgerEquityPoint(
                self._equity_sequence,
                snapshot.ledger_id,
                snapshot.key,
                snapshot.updated_at,
                snapshot.key.base_currency,
                snapshot.capital.initial_capital,
                snapshot.cash.cash_balance,
                snapshot.equity.position_market_value,
                snapshot.pnl.realized_pnl,
                snapshot.pnl.unrealized_pnl,
                snapshot.pnl.fees,
                snapshot.equity.equity,
                snapshot.equity.return_since_start,
                snapshot.equity.drawdown,
                snapshot.equity.maximum_drawdown,
                snapshot.version,
                snapshot.quality_flags,
            )
        )
        return snapshot

    def _publish(
        self, event_type: str, snapshot: OnlyStrategyLedgerSnapshot, timestamp: OnlyTimestamp
    ) -> OnlyStrategyLedgerEvent:
        self._event_sequence += 1
        event = OnlyStrategyLedgerEvent(event_type, snapshot.key, timestamp, self._event_sequence, snapshot.version)
        self._repository.save_event(event)
        self._publisher.publish(event)
        return event

    def _require_entity(self, key: OnlyStrategyLedgerKey) -> OnlyStrategyLedger:
        self._require_scope(key)
        try:
            return self._ledgers[key]
        except KeyError as exc:
            raise KeyError(f"Strategy Ledger not found: {key}") from exc

    def _require_scope(self, key: OnlyStrategyLedgerKey) -> None:
        if key.runtime_id != self.runtime_id:
            raise OnlyStrategyLedgerScopeError("Strategy Ledger belongs to another Runtime")

    @staticmethod
    def _fingerprints(accounting: OnlyStrategyTradeAccountingInput) -> set[str]:
        trade = accounting.trade
        values = {f"trade:{trade.trade_id}"}
        if trade.execution_id:
            values.add(f"execution:{trade.execution_id}")
        if trade.venue_trade_id:
            values.add(f"venue:{trade.venue_trade_id}")
        return values

    @staticmethod
    def _trade_notional(key: OnlyStrategyLedgerKey, accounting: OnlyStrategyTradeAccountingInput) -> OnlyMoney:
        quantum = Decimal(1).scaleb(-key.base_currency.precision)
        value = (
            accounting.trade.price.value * accounting.trade.quantity.value * accounting.trade.multiplier.value
        ).quantize(quantum, ROUND_HALF_EVEN)
        return OnlyMoney(value, key.base_currency)

    @staticmethod
    def _unchanged(
        snapshot: OnlyStrategyLedgerSnapshot, status: OnlyStrategyLedgerMutationStatus
    ) -> OnlyStrategyLedgerMutationResult:
        zero = only_zero_money(snapshot.key.base_currency)
        return OnlyStrategyLedgerMutationResult(status, snapshot, snapshot, zero, zero, zero)

    @staticmethod
    def _result(
        before: OnlyStrategyLedgerSnapshot,
        after: OnlyStrategyLedgerSnapshot,
        events: tuple[OnlyStrategyLedgerEvent, ...],
        *,
        cash_delta: OnlyMoney | None = None,
        fee_delta: OnlyMoney | None = None,
    ) -> OnlyStrategyLedgerMutationResult:
        zero = only_zero_money(after.key.base_currency)
        return OnlyStrategyLedgerMutationResult(
            OnlyStrategyLedgerMutationStatus.APPLIED,
            before,
            after,
            cash_delta or zero,
            zero,
            fee_delta or zero,
            events,
        )
