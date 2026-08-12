"""Runtime-neutral driver continuity evidence for one recovery session."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId, OnlyMarketDataUpdateId
from onlyalpha.domain.time import OnlyTimestamp


@dataclass(frozen=True, slots=True)
class OnlyRuntimeRecoveryBoundary:
    source_id: OnlyMarketDataSourceId
    data_version: OnlyDataVersion
    update_id: OnlyMarketDataUpdateId
    source_sequence: int
    ts_event: OnlyTimestamp

    def __post_init__(self) -> None:
        if self.source_sequence < 1:
            raise ValueError("recovery boundary source sequence must be positive")


@dataclass(frozen=True, slots=True)
class OnlyRuntimeRecoveryDriverResult:
    catch_up_fact_count: int
    final_boundary: OnlyRuntimeRecoveryBoundary
    continuation_transaction_count: int

    def __post_init__(self) -> None:
        if self.catch_up_fact_count < 0 or self.continuation_transaction_count < 0:
            raise ValueError("recovery driver counts cannot be negative")


__all__ = ["OnlyRuntimeRecoveryBoundary", "OnlyRuntimeRecoveryDriverResult"]
