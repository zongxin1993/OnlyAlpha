"""Strategy Ledger persistence and publication ports."""

from typing import Protocol

from onlyalpha.strategy_ledger.models import (
    OnlyStrategyCashEntry,
    OnlyStrategyCashReservation,
    OnlyStrategyFeeEntry,
    OnlyStrategyLedgerEvent,
    OnlyStrategyLedgerSnapshot,
)


class OnlyStrategyLedgerEventPublisher(Protocol):
    def publish(self, event: OnlyStrategyLedgerEvent) -> None: ...


class OnlyStrategyLedgerRepository(Protocol):
    def save(self, snapshot: OnlyStrategyLedgerSnapshot) -> None: ...

    def save_cash_entries(self, entries: tuple[OnlyStrategyCashEntry, ...]) -> None: ...

    def save_fee_entries(self, entries: tuple[OnlyStrategyFeeEntry, ...]) -> None: ...

    def save_reservations(self, entries: tuple[OnlyStrategyCashReservation, ...]) -> None: ...

    def save_event(self, event: OnlyStrategyLedgerEvent) -> None: ...
