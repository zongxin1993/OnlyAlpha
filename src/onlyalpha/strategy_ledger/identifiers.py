"""Strong identifiers for Strategy Ledger records."""

from dataclasses import dataclass

from onlyalpha.domain.identifiers import OnlyIdentifier


@dataclass(frozen=True, slots=True)
class OnlyStrategyLedgerId(OnlyIdentifier):
    pass


@dataclass(frozen=True, slots=True)
class OnlyStrategyCashEntryId(OnlyIdentifier):
    pass


@dataclass(frozen=True, slots=True)
class OnlyStrategyFeeEntryId(OnlyIdentifier):
    pass


@dataclass(frozen=True, slots=True)
class OnlyStrategyCashReservationId(OnlyIdentifier):
    pass


@dataclass(frozen=True, slots=True)
class OnlyStrategyCashFlowId(OnlyIdentifier):
    pass
