"""Strong settlement identities."""

from dataclasses import dataclass

from onlyalpha.domain.identifiers import OnlyIdentifier


@dataclass(frozen=True, slots=True)
class OnlySettlementInstructionId(OnlyIdentifier):
    pass


__all__ = ["OnlySettlementInstructionId"]
