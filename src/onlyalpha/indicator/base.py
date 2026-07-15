"""Indicator identities, requirements, and deterministic update contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from onlyalpha.domain.market import OnlyBar, OnlyBarType


class OnlyStructuredIndicatorValue(ABC):
    """Immutable, explicitly serializable value produced by an Indicator."""

    @property
    @abstractmethod
    def value_type(self) -> str: ...

    @abstractmethod
    def to_dict(self) -> Mapping[str, object]: ...


type OnlyIndicatorValue = Decimal | int | str | bool | OnlyStructuredIndicatorValue | None


@dataclass(frozen=True, order=True, slots=True)
class OnlyIndicatorId:
    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip()
        if not normalized:
            raise ValueError("indicator_id is required")
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


class OnlyIndicatorRequirement(StrEnum):
    REQUIRED = "REQUIRED"
    OPTIONAL = "OPTIONAL"


class OnlyIndicator(ABC):
    """Purely synchronous incremental indicator contract."""

    @property
    @abstractmethod
    def indicator_id(self) -> OnlyIndicatorId: ...

    @property
    @abstractmethod
    def bar_type(self) -> OnlyBarType: ...

    @abstractmethod
    def update(self, bar: OnlyBar, history: tuple[OnlyBar, ...]) -> OnlyIndicatorValue: ...


@dataclass(frozen=True, slots=True)
class OnlyIndicatorRegistration:
    indicator: OnlyIndicator
    requirement: OnlyIndicatorRequirement
