"""Generic indicator creation request and factory contract."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from onlyalpha.calculation.definition import OnlyCalculationTypeReference
from onlyalpha.domain.market import OnlyBarType
from onlyalpha.indicator.base import OnlyBarIndicator
from onlyalpha.indicator.identifiers import (
    OnlyIndicatorId,
    OnlyIndicatorTypeId,
    only_indicator_calculation_reference,
)
from onlyalpha.indicator.snapshot import OnlyIndicatorSnapshot


@dataclass(frozen=True, slots=True)
class OnlyIndicatorCreateRequest:
    indicator_type: OnlyIndicatorTypeId
    indicator_id: OnlyIndicatorId
    bar_type: OnlyBarType
    parameters: Mapping[str, object]

    @property
    def calculation_reference(self) -> OnlyCalculationTypeReference:
        return only_indicator_calculation_reference(self.indicator_type)


class OnlyIndicatorFactory(Protocol):
    @property
    def indicator_type(self) -> OnlyIndicatorTypeId: ...

    def create(self, request: OnlyIndicatorCreateRequest) -> OnlyBarIndicator[OnlyIndicatorSnapshot]: ...


@dataclass(frozen=True, slots=True)
class OnlyIndicatorRegistrationResult:
    indicator_id: OnlyIndicatorId
    created: bool
