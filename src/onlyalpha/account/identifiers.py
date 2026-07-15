"""Account component identifiers."""

from dataclasses import dataclass

from onlyalpha.domain.identifiers import OnlyIdentifier


@dataclass(frozen=True, slots=True)
class OnlyAccountReservationId(OnlyIdentifier):
    pass


@dataclass(frozen=True, slots=True)
class OnlyAccountCashChangeId(OnlyIdentifier):
    pass


@dataclass(frozen=True, slots=True)
class OnlyAccountFeeId(OnlyIdentifier):
    pass
