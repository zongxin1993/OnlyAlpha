"""Internal legacy attribution identifier; never a Strategy semantic identity."""

from dataclasses import dataclass

from onlyalpha.domain.base import OnlyDomainModel


@dataclass(frozen=True, order=True, slots=True)
class OnlyStrategyId(OnlyDomainModel):
    """Trading-fact attribution compatibility only; execution uses strategy_fingerprint."""

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip()
        if not normalized:
            raise ValueError("strategy_id is required")
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value
