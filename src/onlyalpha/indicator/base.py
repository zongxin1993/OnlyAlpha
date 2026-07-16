"""Side-effect-free indicator contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Generic, TypeVar

from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.indicator.identifiers import OnlyIndicatorId, OnlyIndicatorTypeId
from onlyalpha.indicator.score import OnlyIndicatorScore
from onlyalpha.indicator.snapshot import OnlyIndicatorSnapshot, OnlyWarmupProgress

OnlyIndicatorSnapshotT = TypeVar("OnlyIndicatorSnapshotT", bound=OnlyIndicatorSnapshot, covariant=True)


class OnlyStructuredIndicatorValue(ABC):
    @property
    @abstractmethod
    def value_type(self) -> str: ...

    @abstractmethod
    def to_dict(self) -> Mapping[str, object]: ...


type OnlyIndicatorValue = Decimal | int | str | bool | OnlyStructuredIndicatorValue | OnlyIndicatorSnapshot | None


class OnlyIndicatorRequirement(StrEnum):
    REQUIRED = "REQUIRED"
    OPTIONAL = "OPTIONAL"


class OnlyIndicator(ABC, Generic[OnlyIndicatorSnapshotT]):  # noqa: UP046
    """Deterministic lowest-level computation with no trading capabilities."""

    @property
    @abstractmethod
    def indicator_id(self) -> OnlyIndicatorId: ...

    @property
    @abstractmethod
    def indicator_type(self) -> OnlyIndicatorTypeId: ...

    @property
    @abstractmethod
    def ready(self) -> bool: ...

    @property
    @abstractmethod
    def warmup_progress(self) -> OnlyWarmupProgress: ...

    @abstractmethod
    def reset(self) -> None: ...

    @abstractmethod
    def snapshot(self) -> OnlyIndicatorSnapshotT: ...

    def canonical_score(self) -> OnlyIndicatorScore | None:
        return None


class OnlyBarIndicator(OnlyIndicator[OnlyIndicatorSnapshotT], ABC):
    @property
    @abstractmethod
    def bar_type(self) -> OnlyBarType: ...

    @abstractmethod
    def update_bar(self, bar: OnlyBar) -> None: ...


@dataclass(frozen=True, slots=True)
class OnlyIndicatorRegistration:
    """A scoped indicator owned by one Factor."""

    indicator: OnlyBarIndicator[OnlyIndicatorSnapshot]
    requirement: OnlyIndicatorRequirement = OnlyIndicatorRequirement.REQUIRED
