"""Dynamic Factor factory; concrete Indicators are created later by Factor lifecycle."""

from collections.abc import Mapping
from dataclasses import dataclass
from importlib import import_module

from onlyalpha.calculation.definition import OnlyCalculationTypeReference
from onlyalpha.factor.base import OnlyFactor
from onlyalpha.factor.config import OnlyFactorConfig


def only_load_factor_type(path: str) -> type[object]:
    module_name, class_name = path.split(":", 1)
    candidate = getattr(import_module(module_name), class_name)
    if not isinstance(candidate, type):
        raise TypeError(f"{path} does not reference a class")
    return candidate


@dataclass(frozen=True, slots=True)
class OnlyFactorCreateRequest:
    calculation_reference: OnlyCalculationTypeReference
    factor_path: str
    config_path: str
    parameters: Mapping[str, object]


class OnlyFactorFactory:
    def create(self, request: OnlyFactorCreateRequest) -> OnlyFactor:
        config_type = only_load_factor_type(request.config_path)
        factor_type = only_load_factor_type(request.factor_path)
        if not issubclass(config_type, OnlyFactorConfig):
            raise TypeError("Factor config class must derive from OnlyFactorConfig")
        if not issubclass(factor_type, OnlyFactor):
            raise TypeError("Factor class must derive from OnlyFactor")
        actual_reference = getattr(factor_type, "calculation_reference", None)
        if actual_reference != request.calculation_reference:
            raise ValueError("Factor implementation does not match the exact calculation reference")
        from_mapping = getattr(config_type, "from_mapping", None)
        if not callable(from_mapping):
            raise TypeError("Factor config class must define from_mapping()")
        return factor_type(from_mapping(request.parameters))
