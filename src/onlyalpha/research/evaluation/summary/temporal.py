"""Explicit canonical temporal interval contracts for Research summaries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OnlyResearchTemporalSlice:
    start_ts_event_ns: int
    end_ts_event_ns: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.start_ts_event_ns, bool)
            or not isinstance(self.start_ts_event_ns, int)
            or isinstance(self.end_ts_event_ns, bool)
            or not isinstance(self.end_ts_event_ns, int)
        ):
            raise ValueError("Temporal Slice boundaries must be integer nanoseconds")
        if self.start_ts_event_ns >= self.end_ts_event_ns:
            raise ValueError("Temporal Slice requires start < end")

    def to_dict(self) -> dict[str, int]:
        return {
            "start_ts_event_ns": self.start_ts_event_ns,
            "end_ts_event_ns": self.end_ts_event_ns,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchTemporalSlice:
        if set(payload) != {"start_ts_event_ns", "end_ts_event_ns"}:
            raise ValueError("Temporal Slice fields are invalid")
        start = payload["start_ts_event_ns"]
        end = payload["end_ts_event_ns"]
        if isinstance(start, bool) or not isinstance(start, int) or isinstance(end, bool) or not isinstance(end, int):
            raise ValueError("Temporal Slice boundaries must be integer nanoseconds")
        return cls(start, end)


__all__ = ["OnlyResearchTemporalSlice"]
