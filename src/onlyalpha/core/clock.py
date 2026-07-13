"""Clock abstractions shared by live and deterministic runtimes."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime

from onlyalpha.core.errors import OnlyValidationError


class OnlyClock(ABC):
    """Source of time injected into runtime and strategy code."""

    @abstractmethod
    def now(self) -> datetime:
        """Return a timezone-aware timestamp."""


class OnlyLiveClock(OnlyClock):
    """UTC wall clock for live or paper operation."""

    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass
class OnlyBacktestClock(OnlyClock):
    """Explicitly advanced deterministic clock."""

    current_time: datetime

    def __post_init__(self) -> None:
        if self.current_time.tzinfo is None:
            raise OnlyValidationError("backtest clock requires a timezone-aware timestamp")

    def now(self) -> datetime:
        return self.current_time

    def advance_to(self, timestamp: datetime) -> None:
        if timestamp.tzinfo is None:
            raise OnlyValidationError("timestamp must be timezone-aware")
        if timestamp < self.current_time:
            raise OnlyValidationError("backtest clock cannot move backwards")
        self.current_time = timestamp
