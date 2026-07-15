"""Runtime-owned Cluster Position attribution ledger."""

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha.position.enums import OnlyPositionMutationStatus, OnlyPositionSide, OnlySettlementBucket
from onlyalpha.position.exceptions import OnlyPositionOverSellError
from onlyalpha.position.identifiers import OnlyPositionAllocationId
from onlyalpha.position.keys import OnlyPositionAllocationKey
from onlyalpha.position.models import (
    OnlyPositionAllocationSnapshot,
    OnlyPositionTrade,
    OnlySettlementResult,
    OnlyUnallocatedPosition,
    only_zero_quantity,
)
from onlyalpha.position.pnl import OnlyLinearPnLModel, OnlyPnLModel
from onlyalpha.position.ports import OnlyPositionAllocationRepository
from onlyalpha.position.repositories import OnlyInMemoryPositionAllocationRepository


@dataclass(slots=True)
class _OnlyAllocationState:
    allocation_id: OnlyPositionAllocationId
    key: OnlyPositionAllocationKey
    total: OnlyQuantity
    settled: OnlyQuantity
    unsettled: OnlyQuantity
    order_frozen: OnlyQuantity
    risk_reserved: OnlyQuantity
    restricted: OnlyQuantity
    average: OnlyPrice | None
    realized: OnlyMoney
    fees: OnlyMoney
    opened_at: OnlyTimestamp
    updated_at: OnlyTimestamp
    closed_at: OnlyTimestamp | None = None
    version: int = 0
    last_sequence: int | None = None
    last_order: tuple[int, int, str] | None = None

    def snapshot(self) -> OnlyPositionAllocationSnapshot:
        return OnlyPositionAllocationSnapshot(
            self.allocation_id,
            self.key,
            self.total,
            self.settled,
            self.unsettled,
            self.order_frozen,
            self.risk_reserved,
            self.restricted,
            self.average,
            self.realized,
            self.fees,
            self.opened_at,
            self.updated_at,
            self.closed_at,
            self.version,
            self.last_sequence,
            self.last_order,
        )


class OnlyPositionAllocationManager:
    """Cluster attribution ledger; unresolvable trades are never guessed."""

    def __init__(
        self,
        runtime_id: OnlyRuntimeId,
        *,
        pnl_model: OnlyPnLModel | None = None,
        repository: OnlyPositionAllocationRepository | None = None,
    ) -> None:
        self.runtime_id = runtime_id
        self._pnl_model = pnl_model or OnlyLinearPnLModel()
        self._repository = repository or OnlyInMemoryPositionAllocationRepository()
        self._active: dict[OnlyPositionAllocationKey, _OnlyAllocationState] = {}
        self._closed: list[OnlyPositionAllocationSnapshot] = []
        self._unallocated: dict[tuple[OnlyAccountId, OnlyInstrumentId, OnlyPositionSide], OnlyUnallocatedPosition] = {}
        self._trade_fingerprints: set[str] = set()
        self._cycles: dict[OnlyPositionAllocationKey, int] = {}

    def apply_trade(
        self,
        trade: OnlyPositionTrade,
        *,
        own_order_reserved_quantity: OnlyQuantity | None = None,
    ) -> OnlyPositionMutationStatus:
        self._require_scope(trade.runtime_id)
        fingerprints = self._fingerprints(trade)
        if not fingerprints.isdisjoint(self._trade_fingerprints):
            return OnlyPositionMutationStatus.DUPLICATE
        if trade.cluster_id is None:
            self._apply_unallocated_trade(trade, "TRADE_WITHOUT_CLUSTER", "EXECUTION")
            self._trade_fingerprints.update(fingerprints)
            return OnlyPositionMutationStatus.APPLIED
        key = OnlyPositionAllocationKey(
            trade.runtime_id,
            trade.account_id,
            trade.cluster_id,
            trade.instrument_id,
            trade.position_side,
        )
        state = self._active.get(key)
        if state is not None and state.last_order is not None and trade.stable_order < state.last_order:
            return OnlyPositionMutationStatus.STALE
        if state is None:
            if trade.side is OnlyOrderSide.SELL:
                raise OnlyPositionOverSellError("Cluster cannot sell another Cluster's Allocation")
            state = self._new_state(key, trade)
            self._active[key] = state
        self._apply_to_state(state, trade, own_order_reserved_quantity)
        self._trade_fingerprints.update(fingerprints)
        snapshot = state.snapshot()
        self._repository.save(snapshot)
        if snapshot.total_quantity.value == 0:
            self._closed.append(snapshot)
            del self._active[key]
        return OnlyPositionMutationStatus.APPLIED

    def get_snapshot(self, key: OnlyPositionAllocationKey) -> OnlyPositionAllocationSnapshot | None:
        self._require_scope(key.runtime_id)
        state = self._active.get(key)
        return None if state is None else state.snapshot()

    def list_by_cluster(self, cluster_id: OnlyClusterId) -> tuple[OnlyPositionAllocationSnapshot, ...]:
        return tuple(item for item in self.snapshot_all() if item.key.cluster_id == cluster_id)

    def list_by_account(self, account_id: OnlyAccountId) -> tuple[OnlyPositionAllocationSnapshot, ...]:
        return tuple(item for item in self.snapshot_all() if item.key.account_id == account_id)

    def list_by_instrument(self, instrument_id: OnlyInstrumentId) -> tuple[OnlyPositionAllocationSnapshot, ...]:
        return tuple(item for item in self.snapshot_all() if item.key.instrument_id == instrument_id)

    def snapshot_all(self) -> tuple[OnlyPositionAllocationSnapshot, ...]:
        return tuple(sorted((item.snapshot() for item in self._active.values()), key=self._sort_key))

    def closed(self) -> tuple[OnlyPositionAllocationSnapshot, ...]:
        """Return immutable closed Allocation history in deterministic order."""

        return tuple(self._closed)

    def unallocated(self) -> tuple[OnlyUnallocatedPosition, ...]:
        return tuple(
            sorted(self._unallocated.values(), key=lambda item: (str(item.account_id), str(item.instrument_id)))
        )

    def calculate_cluster_available(
        self,
        key: OnlyPositionAllocationKey,
        account_available: OnlyQuantity,
    ) -> OnlyQuantity:
        snapshot = self.get_snapshot(key)
        if snapshot is None:
            return only_zero_quantity(account_available.precision)
        return OnlyQuantity(
            min(snapshot.available_quantity.value, account_available.value),
            max(snapshot.available_quantity.precision, account_available.precision),
        )

    def reserve(self, key: OnlyPositionAllocationKey, quantity: OnlyQuantity) -> OnlyPositionAllocationSnapshot:
        state = self._require_state(key)
        if quantity.value <= 0 or quantity.value > state.snapshot().available_quantity.value:
            raise OnlyPositionOverSellError("Reservation exceeds Cluster Allocation")
        state.risk_reserved = state.risk_reserved + quantity
        state.version += 1
        snapshot = state.snapshot()
        self._repository.save(snapshot)
        return snapshot

    def release(self, key: OnlyPositionAllocationKey, quantity: OnlyQuantity) -> OnlyPositionAllocationSnapshot:
        state = self._require_state(key)
        state.risk_reserved = OnlyQuantity(
            max(state.risk_reserved.value - quantity.value, Decimal(0)),
            state.risk_reserved.precision,
        )
        state.version += 1
        snapshot = state.snapshot()
        self._repository.save(snapshot)
        return snapshot

    def settle(self, key: OnlyPositionAllocationKey, trading_day: OnlyTradingDay) -> OnlySettlementResult:
        state = self._require_state(key)
        before = state.version
        moved = state.unsettled
        if moved.value:
            state.settled = state.settled + moved
            state.unsettled = only_zero_quantity(moved.precision)
            state.version += 1
            self._repository.save(state.snapshot())
        return OnlySettlementResult(trading_day, moved, before, state.version, moved.value > 0)

    def reconcile_unallocated(
        self,
        account_id: OnlyAccountId,
        instrument_id: OnlyInstrumentId,
        position_side: OnlyPositionSide,
        account_total: OnlyQuantity,
        account_settled: OnlyQuantity,
        account_unsettled: OnlyQuantity,
        now: OnlyTimestamp,
    ) -> OnlyUnallocatedPosition | None:
        allocations = tuple(
            item
            for item in self.snapshot_all()
            if item.key.account_id == account_id
            and item.key.instrument_id == instrument_id
            and item.key.position_side == position_side
        )
        allocated_total = sum((item.total_quantity.value for item in allocations), Decimal(0))
        if allocated_total > account_total.value:
            raise ValueError("Cluster Allocations exceed account Position")
        missing = account_total.value - allocated_total
        key = (account_id, instrument_id, position_side)
        if missing == 0:
            self._unallocated.pop(key, None)
            return None
        allocated_settled = sum((item.settled_quantity.value for item in allocations), Decimal(0))
        missing_settled = max(account_settled.value - allocated_settled, Decimal(0))
        missing_unsettled = missing - missing_settled
        previous = self._unallocated.get(key)
        unallocated = OnlyUnallocatedPosition(
            self.runtime_id,
            account_id,
            instrument_id,
            position_side,
            OnlyQuantity(missing, account_total.precision),
            OnlyQuantity(missing_settled, account_total.precision),
            OnlyQuantity(missing_unsettled, account_total.precision),
            "ACCOUNT_ALLOCATION_DIFFERENCE",
            "RECONCILIATION",
            previous.created_at if previous else now,
            now,
            1 if previous is None else previous.version + 1,
        )
        self._unallocated[key] = unallocated
        return unallocated

    def _apply_unallocated_trade(self, trade: OnlyPositionTrade, reason: str, source: str) -> None:
        key = (trade.account_id, trade.instrument_id, trade.position_side)
        previous = self._unallocated.get(key)
        old_total = Decimal(0) if previous is None else previous.total_quantity.value
        delta = trade.quantity.value if trade.side is OnlyOrderSide.BUY else -trade.quantity.value
        total = old_total + delta
        if total < 0:
            raise OnlyPositionOverSellError("unallocated sell exceeds unallocated Position")
        old_settled = Decimal(0) if previous is None else previous.settled_quantity.value
        old_unsettled = Decimal(0) if previous is None else previous.unsettled_quantity.value
        if trade.side is OnlyOrderSide.BUY:
            if trade.settlement_bucket is OnlySettlementBucket.SETTLED:
                old_settled += trade.quantity.value
            else:
                old_unsettled += trade.quantity.value
        else:
            old_settled -= trade.quantity.value
        self._unallocated[key] = OnlyUnallocatedPosition(
            trade.runtime_id,
            trade.account_id,
            trade.instrument_id,
            trade.position_side,
            OnlyQuantity(total, trade.quantity.precision),
            OnlyQuantity(old_settled, trade.quantity.precision),
            OnlyQuantity(old_unsettled, trade.quantity.precision),
            reason,
            source,
            previous.created_at if previous else trade.ts_event,
            trade.ts_event,
            1 if previous is None else previous.version + 1,
        )

    def _new_state(self, key: OnlyPositionAllocationKey, trade: OnlyPositionTrade) -> _OnlyAllocationState:
        cycle = self._cycles.get(key, 0) + 1
        self._cycles[key] = cycle
        zero = only_zero_quantity(trade.quantity.precision)
        return _OnlyAllocationState(
            OnlyPositionAllocationId(
                f"ALLOC-{key.runtime_id}-{key.account_id}-{key.cluster_id}-{key.instrument_id}-{cycle:08d}"
            ),
            key,
            zero,
            zero,
            zero,
            zero,
            zero,
            zero,
            None,
            OnlyMoney(Decimal(0), trade.fee.currency),
            OnlyMoney(Decimal(0), trade.fee.currency),
            trade.ts_event,
            trade.ts_event,
        )

    def _apply_to_state(
        self,
        state: _OnlyAllocationState,
        trade: OnlyPositionTrade,
        own_order_reserved_quantity: OnlyQuantity | None = None,
    ) -> None:
        if trade.side is OnlyOrderSide.BUY:
            old = state.total.value
            new = old + trade.quantity.value
            raw_average = (
                trade.price.value
                if state.average is None
                else (state.average.value * old + trade.price.value * trade.quantity.value) / new
            )
            precision = max(trade.price.precision, state.average.precision if state.average else 0)
            state.average = OnlyPrice(raw_average.quantize(Decimal(1).scaleb(-precision), ROUND_HALF_EVEN), precision)
            state.total = OnlyQuantity(new, trade.quantity.precision)
            if trade.settlement_bucket is OnlySettlementBucket.SETTLED:
                state.settled = state.settled + trade.quantity
            else:
                state.unsettled = state.unsettled + trade.quantity
        else:
            own_reserved = Decimal(0)
            if own_order_reserved_quantity is not None:
                own_reserved = min(own_order_reserved_quantity.value, state.risk_reserved.value)
            effective_available = state.snapshot().available_quantity.value + own_reserved
            if trade.quantity.value > effective_available or state.average is None:
                raise OnlyPositionOverSellError("Cluster sell exceeds its own available Allocation")
            if own_reserved:
                state.risk_reserved = OnlyQuantity(
                    state.risk_reserved.value - own_reserved,
                    state.risk_reserved.precision,
                )
            pnl = self._pnl_model.realized(
                state.key.position_side,
                state.average,
                trade.price,
                trade.quantity,
                trade.multiplier,
                trade.fee.currency,
            )
            state.realized = state.realized + pnl
            state.settled = OnlyQuantity(state.settled.value - trade.quantity.value, state.settled.precision)
            state.total = OnlyQuantity(state.total.value - trade.quantity.value, state.total.precision)
            if state.total.value == 0:
                state.average = None
                state.closed_at = trade.ts_event
        state.fees = state.fees + trade.fee
        state.updated_at = trade.ts_event
        state.version += 1
        state.last_sequence = trade.external_sequence
        state.last_order = trade.stable_order

    def _require_state(self, key: OnlyPositionAllocationKey) -> _OnlyAllocationState:
        self._require_scope(key.runtime_id)
        state = self._active.get(key)
        if state is None:
            raise KeyError(f"Position Allocation not found: {key}")
        return state

    def _require_scope(self, runtime_id: OnlyRuntimeId) -> None:
        if runtime_id != self.runtime_id:
            raise ValueError("Position Allocation input belongs to another Runtime")

    @staticmethod
    def _fingerprints(trade: OnlyPositionTrade) -> set[str]:
        values = {f"trade:{trade.trade_id}"}
        if trade.execution_id:
            values.add(f"execution:{trade.execution_id}")
        if trade.venue_trade_id is not None:
            values.add(f"venue:{trade.venue_trade_id}")
        return values

    @staticmethod
    def _sort_key(item: OnlyPositionAllocationSnapshot) -> tuple[str, str, str]:
        return str(item.key.account_id), str(item.key.cluster_id), str(item.key.instrument_id)
