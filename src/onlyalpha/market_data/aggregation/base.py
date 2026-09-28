"""Market-independent construction executor contracts."""

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

from onlyalpha.domain.market import OnlyBar, OnlyBarType


class OnlyBarAggregationError(Exception):
    """Input cannot be deterministically constructed as a Bar."""


@runtime_checkable
class OnlyMarketDataConstructionExecutor(Protocol):
    """Stateful executor selected by a compiled construction lane."""

    @property
    def target_bar_type(self) -> OnlyBarType: ...

    def accepts(self, fact: object) -> bool: ...

    def process(self, fact: object) -> tuple[object, ...]: ...

    def capture_checkpoint(self) -> object: ...

    def restore_checkpoint(self, payload: object) -> None: ...


class OnlyBarAggregator(ABC):
    @property
    @abstractmethod
    def target_bar_type(self) -> OnlyBarType: ...

    @abstractmethod
    def accepts(self, fact: object) -> bool: ...

    @abstractmethod
    def process(self, fact: object) -> OnlyBar | None: ...

    @abstractmethod
    def capture_checkpoint(self) -> object: ...

    @abstractmethod
    def restore_checkpoint(self, payload: object) -> None: ...
