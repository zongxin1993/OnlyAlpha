"""Validated extension values for long-lived streaming runtimes."""

from collections.abc import Mapping
from dataclasses import dataclass

from .execution import OnlyExecutionSubmissionCapability


@dataclass(frozen=True, slots=True)
class OnlyStreamingRuntimeConfig:
    execution_capability: OnlyExecutionSubmissionCapability
    bootstrap_bars: int = 50
    inbound_queue_capacity: int = 4096
    stale_after_seconds: int = 10

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "OnlyStreamingRuntimeConfig":
        capability = OnlyExecutionSubmissionCapability(str(value.get("execution_capability", "SHADOW")).upper())
        raw_streaming = value.get("streaming", {})
        if not isinstance(raw_streaming, Mapping):
            raise ValueError("runtime.extensions.streaming must be an object")
        raw_bootstrap = raw_streaming.get("bootstrap_bars", 50)
        bootstrap = 50 if raw_bootstrap == "auto" else int(str(raw_bootstrap))
        result = cls(
            capability,
            bootstrap,
            int(str(raw_streaming.get("inbound_queue_capacity", 4096))),
            int(str(raw_streaming.get("stale_after_seconds", 10))),
        )
        if result.bootstrap_bars < 0 or result.inbound_queue_capacity <= 0 or result.stale_after_seconds <= 0:
            raise ValueError("streaming capacities and stale threshold must be positive")
        return result
