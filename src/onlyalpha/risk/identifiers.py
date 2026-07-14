"""Strong Risk identifiers."""

from dataclasses import dataclass

from onlyalpha.domain.identifiers import OnlyIdentifier


@dataclass(frozen=True, slots=True)
class OnlyRiskRuleId(OnlyIdentifier):
    pass


@dataclass(frozen=True, slots=True)
class OnlyRiskProfileId(OnlyIdentifier):
    pass


@dataclass(frozen=True, slots=True)
class OnlyRiskReservationId(OnlyIdentifier):
    pass


@dataclass(frozen=True, slots=True)
class OnlyRiskAuditId(OnlyIdentifier):
    pass
