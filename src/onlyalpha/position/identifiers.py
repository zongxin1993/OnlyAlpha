"""Strong identifiers owned by the Position component."""

from dataclasses import dataclass

from onlyalpha.domain.identifiers import OnlyIdentifier


@dataclass(frozen=True, slots=True)
class OnlyPositionAllocationId(OnlyIdentifier):
    pass


@dataclass(frozen=True, slots=True)
class OnlyPositionRestrictionId(OnlyIdentifier):
    pass


@dataclass(frozen=True, slots=True)
class OnlyPositionReservationId(OnlyIdentifier):
    pass


@dataclass(frozen=True, slots=True)
class OnlyGatewayId(OnlyIdentifier):
    pass
