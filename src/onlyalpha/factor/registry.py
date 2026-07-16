from onlyalpha.factor.base import OnlyFactor
from onlyalpha.factor.identifiers import OnlyFactorId


class OnlyFactorRegistry:
    def __init__(self, factors: tuple[OnlyFactor, ...]) -> None:
        self._factors: dict[OnlyFactorId, OnlyFactor] = {}
        for factor in factors:
            if factor.factor_id in self._factors:
                raise ValueError(f"duplicate factor: {factor.factor_id}")
            self._factors[factor.factor_id] = factor

    def require(self, factor_id: OnlyFactorId) -> OnlyFactor:
        try:
            return self._factors[factor_id]
        except KeyError as exc:
            raise KeyError(f"unknown factor: {factor_id}") from exc

    @property
    def factors(self) -> tuple[OnlyFactor, ...]:
        return tuple(self._factors[key] for key in sorted(self._factors))
