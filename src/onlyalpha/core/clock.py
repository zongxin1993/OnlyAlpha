"""Clock abstractions shared by live and deterministic runtimes."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

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
        self._require_utc(self.current_time)

    def now(self) -> datetime:
        return self.current_time

    def advance_to(self, timestamp: datetime) -> None:
        self._require_utc(timestamp)
        if timestamp < self.current_time:
            raise OnlyValidationError("backtest clock cannot move backwards")
        self.current_time = timestamp

    @staticmethod
    def _require_utc(timestamp: datetime) -> None:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise OnlyValidationError("backtest clock timestamp must not be naive")
        if timestamp.utcoffset() != timedelta(0):
            raise OnlyValidationError("backtest clock timestamp must be UTC")
