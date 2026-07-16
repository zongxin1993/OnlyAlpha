"""Dynamic Factor factory; concrete Indicators are created later by Factor lifecycle."""

from collections.abc import Mapping
from dataclasses import dataclass

from onlyalpha.factor.base import OnlyFactor
from onlyalpha.factor.config import OnlyFactorConfig
from onlyalpha.strategy.factory import only_load_type


@dataclass(frozen=True, slots=True)
class OnlyFactorCreateRequest:
    factor_path: str
    config_path: str
    parameters: Mapping[str, object]


class OnlyFactorFactory:
    def create(self, request: OnlyFactorCreateRequest) -> OnlyFactor:
        config_type = only_load_type(request.config_path)
        factor_type = only_load_type(request.factor_path)
        if not issubclass(config_type, OnlyFactorConfig):
            raise TypeError("Factor config class must derive from OnlyFactorConfig")
        if not issubclass(factor_type, OnlyFactor):
            raise TypeError("Factor class must derive from OnlyFactor")
        from_mapping = getattr(config_type, "from_mapping", None)
        if not callable(from_mapping):
            raise TypeError("Factor config class must define from_mapping()")
        return factor_type(from_mapping(request.parameters))
