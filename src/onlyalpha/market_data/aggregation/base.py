"""Market-independent Bar construction executor contract."""

from abc import ABC, abstractmethod

from onlyalpha.domain.market import OnlyBar, OnlyBarType


class OnlyBarAggregationError(Exception):
    """Input cannot be deterministically constructed as a Bar."""


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
