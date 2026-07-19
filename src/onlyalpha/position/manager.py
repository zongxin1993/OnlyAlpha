"""Runtime-owned account Position state manager."""

from decimal import Decimal

from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyInstrumentId, OnlyPositionId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyMoney, OnlyQuantity
from onlyalpha.position.entities import OnlyPosition
from onlyalpha.position.enums import OnlyPositionMode, OnlyPositionMutationStatus
from onlyalpha.position.events import OnlyNullPositionEventPublisher, OnlyPositionEvent
from onlyalpha.position.exceptions import OnlyPositionOverSellError
from onlyalpha.position.keys import OnlyPositionKey
from onlyalpha.position.models import (
    OnlyPositionMutationResult,
    OnlyPositionRestriction,
    OnlyPositionSnapshot,
    OnlyPositionTrade,
    OnlySettlementResult,
)
from onlyalpha.position.pnl import OnlyLinearPnLModel, OnlyPnLModel
from onlyalpha.position.ports import OnlyPositionEventPublisher, OnlyPositionRepository
from onlyalpha.position.repositories import OnlyInMemoryPositionRepository


class OnlyPositionManager:
    """Single-writer account Position truth for exactly one Runtime."""

    def __init__(
        self,
        runtime_id: OnlyRuntimeId,
        *,
        pnl_model: OnlyPnLModel | None = None,
        repository: OnlyPositionRepository | None = None,
        publisher: OnlyPositionEventPublisher | None = None,
    ) -> None:
        self.runtime_id = runtime_id
        self._pnl_model = pnl_model or OnlyLinearPnLModel()
        self._repository = repository or OnlyInMemoryPositionRepository()
        self._publisher = publisher or OnlyNullPositionEventPublisher()
        self._active: dict[OnlyPositionKey, OnlyPosition] = {}
        self._closed: list[OnlyPositionSnapshot] = []
        self._trade_fingerprints: set[str] = set()
        self._cycles: dict[OnlyPositionKey, int] = {}
        self._event_sequence = 0

    def apply_trade(
        self,
        trade: OnlyPositionTrade,
        own_order_reserved_quantity: OnlyQuantity | None = None,
    ) -> OnlyPositionMutationResult:
        self._require_scope(trade.runtime_id)
        fingerprints = self._fingerprints(trade)
        key = OnlyPositionKey(
            trade.runtime_id,
            trade.account_id,
            trade.instrument_id,
            trade.position_side,
            OnlyPositionMode.NETTING,
        )
        position = self._active.get(key)
        before = position.snapshot() if position is not None else None
        if not fingerprints.isdisjoint(self._trade_fingerprints):
            return self._unchanged(OnlyPositionMutationStatus.DUPLICATE, before, trade, "duplicate Trade")
        if (
            position is not None
            and position.last_trade_order is not None
            and trade.stable_order < position.last_trade_order
        ):
            position.set_reconciling()
            after = position.snapshot()
            self._save(after)
            return OnlyPositionMutationResult(
                OnlyPositionMutationStatus.STALE,
                before,
                after,
                OnlyMoney(Decimal(0), trade.fee.currency),
                trade.fee,
                "stale Trade requires reconciliation",
            )
        if position is None:
            if trade.side is OnlyOrderSide.SELL:
                raise OnlyPositionOverSellError("cannot sell without an active account Position")
            cycle = self._cycles.get(key, 0) + 1
            self._cycles[key] = cycle
            position = OnlyPosition(self._position_id(key, cycle), key, trade)
            self._active[key] = position
        pnl_delta = position.apply_trade(
            trade,
            self._pnl_model,
            own_order_reserved_quantity,
        )
        self._trade_fingerprints.update(fingerprints)
        after = position.snapshot()
        self._save(after)
        if after.status.value == "CLOSED":
            self._closed.append(after)
            del self._active[key]
        event_type = self._event_type(before, after, trade.side)
        self._publish(event_type, after, trade.ts_event)
        return OnlyPositionMutationResult(
            OnlyPositionMutationStatus.APPLIED,
            before,
            after,
            pnl_delta,
            trade.fee,
        )

    def bind_publisher(self, publisher: OnlyPositionEventPublisher) -> None:
        """Bind the Runtime fact adapter before any Position state exists."""

        if self._active or self._closed:
            raise ValueError("Position publisher must bind before Position creation")
        self._publisher = publisher

    def get_snapshot(self, key: OnlyPositionKey) -> OnlyPositionSnapshot | None:
        self._require_scope(key.runtime_id)
        entity = self._active.get(key)
        return None if entity is None else entity.snapshot()

    def require_snapshot(self, key: OnlyPositionKey) -> OnlyPositionSnapshot:
        snapshot = self.get_snapshot(key)
        if snapshot is None:
            raise KeyError(f"Position not found: {key}")
        return snapshot

    def list_open(self) -> tuple[OnlyPositionSnapshot, ...]:
        return tuple(sorted((item.snapshot() for item in self._active.values()), key=self._sort_key))

    def list_by_account(self, account_id: OnlyAccountId) -> tuple[OnlyPositionSnapshot, ...]:
        return tuple(item for item in self.list_open() if item.key.account_id == account_id)

    def list_by_instrument(self, instrument_id: OnlyInstrumentId) -> tuple[OnlyPositionSnapshot, ...]:
        return tuple(item for item in self.list_open() if item.key.instrument_id == instrument_id)

    def snapshot_all(self) -> tuple[OnlyPositionSnapshot, ...]:
        return self.list_open()

    def closed(self) -> tuple[OnlyPositionSnapshot, ...]:
        return tuple(self._closed)

    def freeze(self, key: OnlyPositionKey, quantity: OnlyQuantity, *, risk: bool = False) -> OnlyPositionSnapshot:
        entity = self._require_entity(key)
        entity.freeze(quantity, risk=risk)
        snapshot = entity.snapshot()
        self._save(snapshot)
        return snapshot

    def release(self, key: OnlyPositionKey, quantity: OnlyQuantity, *, risk: bool = False) -> OnlyPositionSnapshot:
        entity = self._require_entity(key)
        entity.release(quantity, risk=risk)
        snapshot = entity.snapshot()
        self._save(snapshot)
        return snapshot

    def apply_restriction(self, restriction: OnlyPositionRestriction) -> OnlyPositionSnapshot:
        entity = self._require_entity(restriction.key)
        entity.apply_restriction(restriction)
        snapshot = entity.snapshot()
        self._save(snapshot)
        return snapshot

    def remove_restriction(self, key: OnlyPositionKey, restriction_id: object) -> OnlyPositionSnapshot:
        entity = self._require_entity(key)
        entity.remove_restriction(restriction_id)
        snapshot = entity.snapshot()
        self._save(snapshot)
        return snapshot

    def settle(self, key: OnlyPositionKey, trading_day: OnlyTradingDay) -> OnlySettlementResult:
        entity = self._require_entity(key)
        before = entity.snapshot()
        moved = entity.settle()
        after = entity.snapshot()
        if moved.value:
            self._save(after)
            self._publish("POSITION_SETTLED", after, after.updated_at)
        return OnlySettlementResult(trading_day, moved, before.version, after.version, moved.value > 0)

    def set_reconciling(self, key: OnlyPositionKey, broker_available: OnlyQuantity | None = None) -> None:
        entity = self._require_entity(key)
        entity.set_reconciling(broker_available)
        self._save(entity.snapshot())

    def clear_reconciling(self, key: OnlyPositionKey) -> None:
        entity = self._require_entity(key)
        entity.clear_reconciling()
        self._save(entity.snapshot())

    def set_broker_available(self, key: OnlyPositionKey, quantity: OnlyQuantity) -> None:
        entity = self._require_entity(key)
        entity.set_broker_available(quantity)
        self._save(entity.snapshot())

    def is_blocked(self, account_id: OnlyAccountId, instrument_id: OnlyInstrumentId) -> bool:
        return any(
            item.key.account_id == account_id
            and item.key.instrument_id == instrument_id
            and item.status.value == "RECONCILING"
            for item in self.list_open()
        )

    def _require_entity(self, key: OnlyPositionKey) -> OnlyPosition:
        self._require_scope(key.runtime_id)
        entity = self._active.get(key)
        if entity is None:
            raise KeyError(f"Position not found: {key}")
        return entity

    def _require_scope(self, runtime_id: OnlyRuntimeId) -> None:
        if runtime_id != self.runtime_id:
            raise ValueError("Position input belongs to another Runtime")

    def _save(self, snapshot: OnlyPositionSnapshot) -> None:
        self._repository.save(snapshot)

    def _publish(self, event_type: str, snapshot: OnlyPositionSnapshot, timestamp: OnlyTimestamp) -> None:
        self._event_sequence += 1
        self._publisher.publish(
            OnlyPositionEvent(
                event_type,
                self.runtime_id,
                snapshot.key.account_id,
                snapshot.key.instrument_id,
                None,
                timestamp,
                self._event_sequence,
                position=snapshot,
            )
        )

    @staticmethod
    def _fingerprints(trade: OnlyPositionTrade) -> set[str]:
        values = {f"trade:{trade.trade_id}"}
        if trade.execution_id:
            values.add(f"execution:{trade.execution_id}")
        if trade.venue_trade_id is not None:
            values.add(f"venue:{trade.venue_trade_id}")
        return values

    @staticmethod
    def _position_id(key: OnlyPositionKey, cycle: int) -> OnlyPositionId:
        return OnlyPositionId(
            f"POS-{key.runtime_id}-{key.account_id}-{key.instrument_id}-{key.position_side.value}-{cycle:08d}"
        )

    @staticmethod
    def _sort_key(snapshot: OnlyPositionSnapshot) -> tuple[str, str, str]:
        return str(snapshot.key.account_id), str(snapshot.key.instrument_id), snapshot.position_side.value

    @staticmethod
    def _event_type(
        before: OnlyPositionSnapshot | None,
        after: OnlyPositionSnapshot,
        side: OnlyOrderSide,
    ) -> str:
        if before is None:
            return "POSITION_OPENED"
        if after.total_quantity.value == 0:
            return "POSITION_CLOSED"
        return "POSITION_INCREASED" if side is OnlyOrderSide.BUY else "POSITION_REDUCED"

    @staticmethod
    def _unchanged(
        status: OnlyPositionMutationStatus,
        snapshot: OnlyPositionSnapshot | None,
        trade: OnlyPositionTrade,
        reason: str,
    ) -> OnlyPositionMutationResult:
        return OnlyPositionMutationResult(
            status,
            snapshot,
            snapshot,
            OnlyMoney(Decimal(0), trade.fee.currency),
            trade.fee,
            reason,
        )
