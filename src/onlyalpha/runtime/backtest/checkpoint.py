"""Backtest-owned replay frontier checkpoint contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId, OnlyMarketDataUpdateId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.runtime.checkpoint.codec import only_decode_checkpoint_component
from onlyalpha.runtime.checkpoint.model import OnlyRuntimeCheckpoint


@dataclass(frozen=True, slots=True)
class OnlyBacktestReplayCursor:
    source_id: OnlyMarketDataSourceId
    data_version: OnlyDataVersion
    last_update_id: OnlyMarketDataUpdateId | None
    last_source_sequence: int
    last_event_time: OnlyTimestamp | None
    processed_bar_count: int

    def __post_init__(self) -> None:
        if self.last_source_sequence < 0 or self.processed_bar_count < 0:
            raise ValueError("replay cursor sequences cannot be negative")
        if (self.last_update_id is None) != (self.last_event_time is None):
            raise ValueError("replay cursor update identity and event time must be both empty or both present")

    def to_checkpoint(self) -> object:
        return {
            "data_version": str(self.data_version),
            "last_event_time_ns": None if self.last_event_time is None else self.last_event_time.unix_nanos,
            "last_source_sequence": self.last_source_sequence,
            "last_update_id": None if self.last_update_id is None else str(self.last_update_id),
            "processed_bar_count": self.processed_bar_count,
            "source_id": str(self.source_id),
        }

    @classmethod
    def from_checkpoint(cls, payload: object) -> OnlyBacktestReplayCursor:
        if not isinstance(payload, Mapping):
            raise ValueError("Backtest replay frontier checkpoint must be an object")
        update_id = payload["last_update_id"]
        event_ns = payload["last_event_time_ns"]
        return cls(
            OnlyMarketDataSourceId(str(payload["source_id"])),
            OnlyDataVersion(str(payload["data_version"])),
            None if update_id is None else OnlyMarketDataUpdateId(str(update_id)),
            int(payload["last_source_sequence"]),
            None if event_ns is None else OnlyTimestamp.from_unix_nanos(int(event_ns)),
            int(payload["processed_bar_count"]),
        )


def only_backtest_replay_cursor(checkpoint: OnlyRuntimeCheckpoint) -> OnlyBacktestReplayCursor:
    component = next(
        (item for item in checkpoint.components if item.component_id == "backtest.replay-frontier"),
        None,
    )
    if component is None:
        raise RuntimeError("BACKTEST_REPLAY_FRONTIER_CHECKPOINT_MISSING")
    return OnlyBacktestReplayCursor.from_checkpoint(only_decode_checkpoint_component(component))


__all__ = ["OnlyBacktestReplayCursor", "only_backtest_replay_cursor"]
