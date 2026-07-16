from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from onlyalpha.factor.identifiers import OnlyFactorId
from onlyalpha.strategy.identifiers import OnlyStrategyId


@dataclass(frozen=True, slots=True)
class OnlyStrategyConfig:
    strategy_id: OnlyStrategyId
    required_factor_ids: tuple[OnlyFactorId, ...] = ()
    extensions: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if len(self.required_factor_ids) != len(set(self.required_factor_ids)):
            raise ValueError("required Factor IDs must be unique")
        object.__setattr__(self, "extensions", MappingProxyType(dict(self.extensions)))
