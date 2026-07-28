"""Deterministic in-memory Strategy Ledger repository."""

from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey
from onlyalpha.strategy_ledger.models import (
    OnlyStrategyCashEntry,
    OnlyStrategyCashReservation,
    OnlyStrategyFeeEntry,
    OnlyStrategyLedgerEvent,
    OnlyStrategyLedgerSnapshot,
)


class OnlyInMemoryStrategyLedgerRepository:
    def __init__(self) -> None:
        self.snapshots: dict[OnlyStrategyLedgerKey, OnlyStrategyLedgerSnapshot] = {}
        self.cash_entries: dict[str, OnlyStrategyCashEntry] = {}
        self.fee_entries: dict[str, OnlyStrategyFeeEntry] = {}
        self.reservations: dict[str, OnlyStrategyCashReservation] = {}
        self.events: list[OnlyStrategyLedgerEvent] = []

    def save(self, snapshot: OnlyStrategyLedgerSnapshot) -> None:
        self.snapshots[snapshot.key] = snapshot

    def save_cash_entries(self, entries: tuple[OnlyStrategyCashEntry, ...]) -> None:
        self.cash_entries.update((str(item.entry_id), item) for item in entries)

    def save_fee_entries(self, entries: tuple[OnlyStrategyFeeEntry, ...]) -> None:
        self.fee_entries.update((str(item.entry_id), item) for item in entries)

    def save_reservations(self, entries: tuple[OnlyStrategyCashReservation, ...]) -> None:
        self.reservations.update((str(item.reservation_id), item) for item in entries)

    def save_event(self, event: OnlyStrategyLedgerEvent) -> None:
        self.events.append(event)

    def replace_execution_authority(self, snapshot: OnlyStrategyLedgerSnapshot) -> None:
        snapshots = dict(self.snapshots)
        cash_entries = dict(self.cash_entries)
        fee_entries = dict(self.fee_entries)
        snapshots[snapshot.key] = snapshot
        cash_entries.update((str(item.entry_id), item) for item in snapshot.cash_entries)
        fee_entries.update((str(item.entry_id), item) for item in snapshot.fee_entries)
        self.snapshots = snapshots
        self.cash_entries = cash_entries
        self.fee_entries = fee_entries
