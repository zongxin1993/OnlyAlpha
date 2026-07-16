"""Shared Factor configuration values."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from onlyalpha.domain.market import OnlyBarType
from onlyalpha.factor.identifiers import OnlyFactorId
from onlyalpha.indicator.identifiers import OnlyIndicatorId, OnlyIndicatorTypeId


class OnlyFactorType(StrEnum):
    TIME_SERIES = "TIME_SERIES"
    CROSS_SECTION = "CROSS_SECTION"


@dataclass(frozen=True, slots=True)
class OnlyIndicatorSpec:
    indicator_id: OnlyIndicatorId
    indicator_type: OnlyIndicatorTypeId
    bar_type: OnlyBarType
    parameters: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True, slots=True)
class OnlyFactorConfig:
    factor_id: OnlyFactorId
    factor_type: OnlyFactorType
    indicators: tuple[OnlyIndicatorSpec, ...] = ()
    dependencies: tuple[OnlyFactorId, ...] = ()
    required: bool = True
    extensions: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        ids = [item.indicator_id for item in self.indicators]
        if len(ids) != len(set(ids)):
            raise ValueError(f"factor {self.factor_id} has duplicate indicator_id")
        object.__setattr__(self, "extensions", MappingProxyType(dict(self.extensions)))
