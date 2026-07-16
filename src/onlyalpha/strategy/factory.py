"""Dynamic Strategy factory; it never creates Factors or Indicators."""

from collections.abc import Mapping
from dataclasses import dataclass
from importlib import import_module

from onlyalpha.strategy.base import OnlyStrategy
from onlyalpha.strategy.config import OnlyStrategyConfig


@dataclass(frozen=True, slots=True)
class OnlyStrategyCreateRequest:
    strategy_path: str
    config_path: str
    parameters: Mapping[str, object]


def only_load_type(path: str) -> type[object]:
    module_name, class_name = path.split(":", 1)
    candidate = getattr(import_module(module_name), class_name)
    if not isinstance(candidate, type):
        raise TypeError(f"{path} does not reference a class")
    return candidate


class OnlyStrategyFactory:
    def create(self, request: OnlyStrategyCreateRequest) -> OnlyStrategy:
        config_type = only_load_type(request.config_path)
        strategy_type = only_load_type(request.strategy_path)
        if not issubclass(config_type, OnlyStrategyConfig):
            raise TypeError("Strategy config class must derive from OnlyStrategyConfig")
        if not issubclass(strategy_type, OnlyStrategy):
            raise TypeError("Strategy class must derive from OnlyStrategy")
        from_mapping = getattr(config_type, "from_mapping", None)
        if not callable(from_mapping):
            raise TypeError("Strategy config class must define from_mapping()")
        return strategy_type(from_mapping(request.parameters))
