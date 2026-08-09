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
    OnlyStrategyCashReservation,
    OnlyStrategyFeeEntry,
    OnlyStrategyLedgerEquityPoint,
    OnlyStrategyLedgerEvent,
    OnlyStrategyLedgerMutationResult,
    OnlyStrategyLedgerSnapshot,
    OnlyStrategyTradeAccountingInput,
    OnlyStrategyValuation,
    OnlyStrategyValuationLine,
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
        self._cash_reserved: dict[OnlyStrategyLedgerKey, OnlyMoney] = {}
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
        self._cash_reserved[key] = only_zero_money(key.base_currency)
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
        self._cash_reserved[key] = self._reservations[key].active_reserved()
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
            self._cash_reserved[key] = self._reservations[key].active_reserved()
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
        self._cash_reserved[key] = self._reservations[key].active_reserved()
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
        _, changed = self._reservations[key].consume(order_id, actual_amount, timestamp)
        if changed:
            self._cash_reserved[key] = self._reservations[key].active_reserved()
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

    def execution_valuation_lines(self, key: OnlyStrategyLedgerKey) -> tuple[OnlyStrategyValuationLine, ...]:
        """Capture immutable valuation authority for durable lifecycle planning."""

        ledger = self._require_entity(key)
        return tuple(sorted(ledger._valuation_lines.values(), key=lambda item: str(item.instrument_id)))

    @property
    def execution_event_sequence(self) -> int:
        return self._event_sequence

    def restore_execution_event_sequence(self, sequence: int) -> None:
        if sequence < self._event_sequence:
            raise ValueError("Strategy Ledger event sequence cannot regress")
        self._event_sequence = sequence

    def get_cash_reservation(
        self, key: OnlyStrategyLedgerKey, order_id: OnlyOrderId
    ) -> OnlyStrategyCashReservation | None:
        return self._reservations[key].get(order_id)

    def restore_valuation_version(self, key: OnlyStrategyLedgerKey, version: int) -> None:
        if version < 1:
            raise ValueError("Strategy Ledger valuation version must be positive")
        self._valuation_versions[key] = version

    def restore_execution_equity_points(self, points: tuple[OnlyStrategyLedgerEquityPoint, ...]) -> None:
        self.validate_execution_equity_points(points)
        for point in points:
            if point.sequence <= self._equity_sequence:
                continue
            self._equity_timelines.setdefault(point.key, []).append(point)
            self._equity_sequence = point.sequence

    def restore_execution_equity_sequence_head(self, sequence: int) -> None:
        """Restore a bootstrap sequence head for an ordered transaction tail."""

        if sequence < self._equity_sequence:
            raise ValueError("Strategy Ledger equity sequence cannot regress")
        self._equity_sequence = sequence

    @property
    def equity_sequence_head(self) -> int:
        """Return the Runtime-global deterministic Strategy Ledger equity sequence."""

        return self._equity_sequence

    def validate_execution_equity_points(self, points: tuple[OnlyStrategyLedgerEquityPoint, ...]) -> None:
        installed = {point.sequence: point for values in self._equity_timelines.values() for point in values}
        next_sequence = self._equity_sequence + 1
        for point in points:
            if point.key.runtime_id != self.runtime_id:
                raise ValueError("Strategy Ledger equity replay points are out of scope or sequence")
            if point.sequence <= self._equity_sequence:
                if installed.get(point.sequence) != point:
                    raise ValueError("Strategy Ledger equity replay point conflicts with installed authority")
                continue
            if point.sequence != next_sequence:
                raise ValueError("Strategy Ledger equity replay points are out of scope or sequence")
            next_sequence += 1

    def restore_execution_authority(
        self,
        snapshot: OnlyStrategyLedgerSnapshot,
        *,
        trade_fingerprints: tuple[str, ...],
        valuation_lines: tuple[OnlyStrategyValuationLine, ...],
    ) -> None:
        current = self._require_entity(snapshot.key)
        if current.ledger_id != snapshot.ledger_id:
            raise ValueError("Strategy Ledger replay identity mismatch")
        ledger = OnlyStrategyLedger(
            snapshot.ledger_id, snapshot.key, snapshot.capital.initial_capital, snapshot.created_at
        )
        ledger.status = snapshot.status
        ledger.initial_capital = snapshot.capital.initial_capital
        ledger.external_cash_flow = snapshot.capital.external_cash_flow
        ledger.ledger_cash = snapshot.cash.ledger_cash
        ledger.position_cost = snapshot.equity.position_cost
        ledger.position_market_value = snapshot.equity.position_market_value
        ledger.realized_pnl = snapshot.pnl.realized_pnl
        ledger.unrealized_pnl = snapshot.pnl.unrealized_pnl
        ledger.fees = snapshot.pnl.fees
        ledger._equity = snapshot.equity.equity
        ledger.high_water_mark = snapshot.equity.high_water_mark
        ledger.maximum_drawdown = snapshot.equity.maximum_drawdown
        ledger.created_at = snapshot.created_at
        ledger.updated_at = snapshot.updated_at
        ledger.valuation_time = snapshot.valuation_time
        ledger.version = snapshot.version
        ledger.last_trade_sequence = snapshot.last_trade_sequence
        ledger.last_trade_order = snapshot.last_trade_order
        ledger.quality_flags = snapshot.quality_flags
        ledger.cash_entries = list(snapshot.cash_entries)
        ledger.fee_entries = list(snapshot.fee_entries)
        ledger.trade_count = snapshot.performance.trade_count
        ledger.realized_pnl_delta_count = snapshot.performance.realized_pnl_delta_count
        ledger.winning_trade_count = snapshot.performance.winning_trade_count
        ledger.losing_trade_count = snapshot.performance.losing_trade_count
        ledger.gross_profit = snapshot.performance.gross_profit
        ledger.gross_loss = snapshot.performance.gross_loss
        ledger.trading_day = snapshot.equity.trading_day
        ledger.day_start_equity = snapshot.equity.equity - snapshot.equity.daily_pnl
        ledger._valuation_lines = {item.instrument_id: item for item in valuation_lines}
        ledger._entry_sequence = max((item.sequence for item in snapshot.cash_entries), default=0)
        scope_index = dict(self._scope_index)
        trade_index = set(self._trade_fingerprints)
        fee_index = set(self._fee_ids)
        cash_reserved = dict(self._cash_reserved)
        scope_index[
            (snapshot.key.runtime_id, snapshot.key.account_id, snapshot.key.cluster_id, snapshot.key.base_currency)
        ] = snapshot.key
        trade_index.update(trade_fingerprints)
        fee_index.update(item.entry_id for item in snapshot.fee_entries)
        cash_reserved[snapshot.key] = snapshot.cash.cash_reserved
        self._repository.replace_execution_authority(snapshot)
        self._ledgers[snapshot.key] = ledger
        self._reservations.setdefault(snapshot.key, OnlyStrategyCashReservationManager(snapshot.key))
        self._equity_timelines.setdefault(snapshot.key, [])
        self._scope_index = scope_index
        self._trade_fingerprints = trade_index
        self._fee_ids = fee_index
        self._cash_reserved = cash_reserved

    def capture_checkpoint(self) -> object:
        """Capture ledger economics, timelines, reservations, and idempotency heads."""

        return {
            "cash_flow_ids": sorted(str(item) for item in self._cash_flow_ids),
            "equity_sequence": self._equity_sequence,
            "event_sequence": self._event_sequence,
            "ledgers": [item.to_json() for item in self.list_ledgers()],
            "timelines": [
                point.to_json()
                for point in sorted(
                    (point for values in self._equity_timelines.values() for point in values),
                    key=lambda item: item.sequence,
                )
            ],
            "trade_fingerprints": sorted(self._trade_fingerprints),
            "valuation_lines": [
                [key.to_json(), [item.to_json() for item in self._ledgers[key]._valuation_lines.values()]]
                for key in sorted(self._ledgers, key=lambda item: item.to_json())
            ],
            "valuation_versions": [
                [key.to_json(), version]
                for key, version in sorted(self._valuation_versions.items(), key=lambda item: item[0].to_json())
            ],
        }

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, dict):
            raise ValueError("Strategy Ledger checkpoint must be an object")
        lines = {
            OnlyStrategyLedgerKey.from_json(str(key)): tuple(
                OnlyStrategyValuationLine.from_json(str(item)) for item in values
            )
            for key, values in payload["valuation_lines"]
        }
        fingerprints = tuple(str(item) for item in payload["trade_fingerprints"])
        for raw in payload["ledgers"]:
            snapshot = OnlyStrategyLedgerSnapshot.from_json(str(raw))
            self.restore_execution_authority(
                snapshot,
                trade_fingerprints=fingerprints,
                valuation_lines=lines.get(snapshot.key, ()),
            )
            for reservation in snapshot.reservations:
                self.restore_cash_reservation_execution_authority(reservation)
        points = tuple(
            sorted(
                (OnlyStrategyLedgerEquityPoint.from_json(str(item)) for item in payload["timelines"]),
                key=lambda item: item.sequence,
            )
        )
        equity_sequence = int(payload["equity_sequence"])
        sequences = tuple(item.sequence for item in points)
        if (
            len(sequences) != len(set(sequences))
            or (sequences and max(sequences) != equity_sequence)
            or any(item.key not in self._ledgers or item.key.runtime_id != self.runtime_id for item in points)
        ):
            raise ValueError("Strategy Ledger checkpoint equity authority is inconsistent")
        restored_timelines: dict[OnlyStrategyLedgerKey, list[OnlyStrategyLedgerEquityPoint]] = {
            key: [] for key in self._ledgers
        }
        for point in points:
            restored_timelines[point.key].append(point)
        self._equity_timelines = restored_timelines
        self._equity_sequence = equity_sequence
        for key, version in payload["valuation_versions"]:
            self.restore_valuation_version(OnlyStrategyLedgerKey.from_json(str(key)), int(version))
        self._cash_flow_ids.update(OnlyStrategyCashFlowId(str(item)) for item in payload["cash_flow_ids"])
        self.restore_execution_event_sequence(int(payload["event_sequence"]))

    def restore_execution_indexes(
        self,
        snapshot: OnlyStrategyLedgerSnapshot,
        *,
        trade_fingerprints: tuple[str, ...],
        valuation_lines: tuple[OnlyStrategyValuationLine, ...],
    ) -> None:
        """Repair replay indexes without reinstalling economic Ledger state."""

        ledger = self._require_entity(snapshot.key)
        if ledger.ledger_id != snapshot.ledger_id:
            raise ValueError("Strategy Ledger replay identity mismatch")
        scope = (snapshot.key.runtime_id, snapshot.key.account_id, snapshot.key.cluster_id, snapshot.key.base_currency)
        existing_scope = self._scope_index.get(scope)
        if existing_scope not in {None, snapshot.key}:
            raise ValueError("Strategy Ledger replay scope index conflicts with installed authority")
        self._scope_index[scope] = snapshot.key
        self._trade_fingerprints.update(trade_fingerprints)
        self._fee_ids.update(item.entry_id for item in snapshot.fee_entries)
        self._cash_reserved[snapshot.key] = snapshot.cash.cash_reserved
        ledger._valuation_lines = {item.instrument_id: item for item in valuation_lines}
        ledger._entry_sequence = max((item.sequence for item in snapshot.cash_entries), default=0)

    def _snapshot(self, ledger: OnlyStrategyLedger) -> OnlyStrategyLedgerSnapshot:
        reservations = self._reservations[ledger.key]
        cash_reserved = self._cash_reserved.get(ledger.key, reservations.active_reserved())
        return ledger.snapshot(cash_reserved, reservations.snapshots())

    def restore_cash_reservation_execution_authority(self, reservation: OnlyStrategyCashReservation) -> None:
        manager = self._reservations[reservation.key]
        manager.restore_execution_authority(reservation)
        self._cash_reserved[reservation.key] = manager.active_reserved()
        ledger = self._require_entity(reservation.key)
        snapshot = self._snapshot(ledger)
        self._repository.save(snapshot)
        self._repository.save_cash_entries(snapshot.cash_entries)
        self._repository.save_fee_entries(snapshot.fee_entries)
        self._repository.save_reservations(snapshot.reservations)

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
                snapshot.cash.ledger_cash,
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
