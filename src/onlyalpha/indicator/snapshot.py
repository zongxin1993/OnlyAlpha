"""Common immutable indicator output."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass

from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.indicator.identifiers import OnlyIndicatorId


@dataclass(frozen=True, slots=True)
class OnlyWarmupProgress:
    samples: int
    required: int

    def __post_init__(self) -> None:
        if self.samples < 0 or self.required <= 0:
            raise ValueError("warmup progress must be non-negative with a positive requirement")

    @property
    def ratio(self) -> float:
        return min(self.samples, self.required) / self.required

    @property
    def ready(self) -> bool:
        return self.samples >= self.required


class OnlyIndicatorSnapshot(ABC):
    indicator_id: OnlyIndicatorId
    ready: bool
    ts_event: OnlyTimestamp | None

    @abstractmethod
    def to_dict(self) -> Mapping[str, object]: ...
