"""Plugin-owned latency models; no sleep or wall-clock reads."""

from dataclasses import dataclass
from typing import Protocol


class OnlyLatencyModel(Protocol):
    @property
    def submit_latency_ns(self) -> int: ...

    @property
    def acceptance_latency_ns(self) -> int: ...

    @property
    def fill_latency_ns(self) -> int: ...

    @property
    def cancel_latency_ns(self) -> int: ...

    @property
    def query_latency_ns(self) -> int: ...


@dataclass(frozen=True, slots=True)
class OnlyZeroLatencyModel:
    submit_latency_ns: int = 0
    acceptance_latency_ns: int = 0
    fill_latency_ns: int = 0
    cancel_latency_ns: int = 0
    query_latency_ns: int = 0


@dataclass(frozen=True, slots=True)
class OnlyFixedLatencyModel:
    submit_latency_ns: int
    acceptance_latency_ns: int
    fill_latency_ns: int
    cancel_latency_ns: int
    query_latency_ns: int = 0

    def __post_init__(self) -> None:
        if (
            min(
                self.submit_latency_ns,
                self.acceptance_latency_ns,
                self.fill_latency_ns,
                self.cancel_latency_ns,
                self.query_latency_ns,
            )
            < 0
        ):
            raise ValueError("Broker latency cannot be negative")
