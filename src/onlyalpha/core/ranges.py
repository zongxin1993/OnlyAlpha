"""Deterministic UTC half-open time ranges."""

from dataclasses import dataclass
from datetime import datetime

from onlyalpha.domain.time import only_require_utc


@dataclass(frozen=True, slots=True, order=True)
class OnlyTimeRange:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        only_require_utc(self.start, "time range start")
        only_require_utc(self.end, "time range end")
        if self.start >= self.end:
            raise ValueError("time range must be increasing and is [start, end)")

    def contains(self, value: datetime) -> bool:
        only_require_utc(value, "time range value")
        return self.start <= value < self.end

    def overlaps(self, other: "OnlyTimeRange") -> bool:
        return self.start < other.end and other.start < self.end

    def intersection(self, other: "OnlyTimeRange") -> "OnlyTimeRange | None":
        start, end = max(self.start, other.start), min(self.end, other.end)
        return OnlyTimeRange(start, end) if start < end else None

    def subtract(self, other: "OnlyTimeRange") -> tuple["OnlyTimeRange", ...]:
        overlap = self.intersection(other)
        if overlap is None:
            return (self,)
        result: list[OnlyTimeRange] = []
        if self.start < overlap.start:
            result.append(OnlyTimeRange(self.start, overlap.start))
        if overlap.end < self.end:
            result.append(OnlyTimeRange(overlap.end, self.end))
        return tuple(result)


def only_merge_ranges(ranges: tuple[OnlyTimeRange, ...]) -> tuple[OnlyTimeRange, ...]:
    if not ranges:
        return ()
    merged: list[OnlyTimeRange] = []
    for item in sorted(ranges):
        if not merged or merged[-1].end < item.start:
            merged.append(item)
        else:
            previous = merged[-1]
            merged[-1] = OnlyTimeRange(previous.start, max(previous.end, item.end))
    return tuple(merged)


def only_missing_ranges(requested: OnlyTimeRange, coverage: tuple[OnlyTimeRange, ...]) -> tuple[OnlyTimeRange, ...]:
    missing: tuple[OnlyTimeRange, ...] = (requested,)
    for covered in only_merge_ranges(coverage):
        missing = tuple(part for item in missing for part in item.subtract(covered))
    return missing
