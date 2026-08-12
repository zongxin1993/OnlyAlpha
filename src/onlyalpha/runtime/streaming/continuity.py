"""Canonical closed-market-fact frontier for Streaming runtimes."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass

from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId, OnlyMarketDataUpdateId
from onlyalpha.data.models import OnlyBarUpdate, OnlyMarketDataInboundUpdate
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp


@dataclass(frozen=True, slots=True)
class OnlyStreamingStreamKey:
    source_id: OnlyMarketDataSourceId
    data_version: OnlyDataVersion
    instrument_id: OnlyInstrumentId
    data_type: OnlyMarketDataType
    bar_type: OnlyBarType

    @property
    def canonical(self) -> str:
        return "|".join(
            (
                str(self.source_id),
                str(self.data_version),
                str(self.instrument_id),
                self.data_type.value,
                self.bar_type.to_json(),
            )
        )


@dataclass(frozen=True, slots=True)
class OnlyStreamingStreamFrontier:
    key: OnlyStreamingStreamKey
    last_closed_bar_start: OnlyTimestamp
    last_closed_bar_end: OnlyTimestamp
    last_update_id: OnlyMarketDataUpdateId
    canonical_sequence: int
    provider_sequence: int | None
    processed_count: int


class OnlyStreamingContinuityTracker:
    """Own monotonic Streaming frontiers and bounded overlap dedup state."""

    checkpoint_schema_version = 1

    def __init__(self, *, dedup_capacity: int = 4096) -> None:
        if dedup_capacity < 1:
            raise ValueError("Streaming continuity dedup capacity must be positive")
        self._capacity = dedup_capacity
        self._frontiers: dict[str, OnlyStreamingStreamFrontier] = {}
        self._recent: deque[tuple[str, int]] = deque()
        self._recent_set: set[tuple[str, int]] = set()

    @staticmethod
    def key(update: OnlyMarketDataInboundUpdate) -> OnlyStreamingStreamKey:
        if not isinstance(update.payload, OnlyBarUpdate):
            raise ValueError("Streaming continuity currently requires a Bar update")
        return OnlyStreamingStreamKey(
            update.source_id,
            update.data_version,
            update.instrument_id,
            update.data_type,
            update.payload.bar.bar_type,
        )

    def contains(self, update: OnlyMarketDataInboundUpdate) -> bool:
        if not isinstance(update.payload, OnlyBarUpdate):
            return False
        key = self.key(update).canonical
        identity = (key, OnlyTimestamp.from_datetime(update.payload.bar.bar_start).unix_nanos)
        frontier = self._frontiers.get(key)
        return identity in self._recent_set or (
            frontier is not None
            and OnlyTimestamp.from_datetime(update.payload.bar.bar_end).unix_nanos
            <= frontier.last_closed_bar_end.unix_nanos
        )

    def advance(self, update: OnlyMarketDataInboundUpdate) -> OnlyStreamingStreamFrontier:
        if not isinstance(update.payload, OnlyBarUpdate) or not update.payload.bar.is_closed:
            raise ValueError("Streaming continuity advances only with closed Bars")
        key = self.key(update)
        canonical = key.canonical
        bar = update.payload.bar
        start = OnlyTimestamp.from_datetime(bar.bar_start)
        end = OnlyTimestamp.from_datetime(bar.bar_end)
        previous = self._frontiers.get(canonical)
        if previous is not None and end.unix_nanos <= previous.last_closed_bar_end.unix_nanos:
            raise ValueError("STREAMING_CONTINUITY_FRONTIER_NOT_MONOTONIC")
        provider = next((int(value) for name, value in update.metadata if name == "provider_sequence"), None)
        frontier = OnlyStreamingStreamFrontier(
            key,
            start,
            end,
            update.update_id,
            int(update.source_sequence),
            provider,
            1 if previous is None else previous.processed_count + 1,
        )
        self._frontiers[canonical] = frontier
        identity = (canonical, start.unix_nanos)
        self._recent.append(identity)
        self._recent_set.add(identity)
        while len(self._recent) > self._capacity:
            self._recent_set.discard(self._recent.popleft())
        return frontier

    @property
    def frontiers(self) -> tuple[OnlyStreamingStreamFrontier, ...]:
        return tuple(self._frontiers[key] for key in sorted(self._frontiers))

    @property
    def last_closed_bar_end(self) -> OnlyTimestamp | None:
        return max((item.last_closed_bar_end for item in self._frontiers.values()), default=None)

    def accepted_sequence(self, source_id: OnlyMarketDataSourceId, data_type: OnlyMarketDataType) -> int:
        return max(
            (
                item.canonical_sequence
                for item in self._frontiers.values()
                if item.key.source_id == source_id and item.key.data_type is data_type
            ),
            default=0,
        )

    def capture_checkpoint(self) -> object:
        return {
            "dedup_capacity": self._capacity,
            "frontiers": [
                {
                    "bar_type": item.key.bar_type.to_json(),
                    "canonical_sequence": item.canonical_sequence,
                    "data_type": item.key.data_type.value,
                    "data_version": str(item.key.data_version),
                    "instrument_id": str(item.key.instrument_id),
                    "last_closed_bar_end_ns": item.last_closed_bar_end.unix_nanos,
                    "last_closed_bar_start_ns": item.last_closed_bar_start.unix_nanos,
                    "last_update_id": str(item.last_update_id),
                    "processed_count": item.processed_count,
                    "provider_sequence": item.provider_sequence,
                    "source_id": str(item.key.source_id),
                }
                for item in self.frontiers
            ],
            "recent": [[key, start] for key, start in self._recent],
        }

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, Mapping):
            raise ValueError("Streaming continuity checkpoint must be an object")
        raw_frontiers = payload["frontiers"]
        raw_recent = payload["recent"]
        if not isinstance(raw_frontiers, list) or not isinstance(raw_recent, list):
            raise ValueError("Streaming continuity checkpoint arrays are required")
        self._capacity = int(payload["dedup_capacity"])
        self._frontiers.clear()
        for raw in raw_frontiers:
            if not isinstance(raw, Mapping):
                raise ValueError("Streaming continuity frontier must be an object")
            key = OnlyStreamingStreamKey(
                OnlyMarketDataSourceId(str(raw["source_id"])),
                OnlyDataVersion(str(raw["data_version"])),
                OnlyInstrumentId.parse(str(raw["instrument_id"])),
                OnlyMarketDataType(str(raw["data_type"])),
                OnlyBarType.from_json(str(raw["bar_type"])),
            )
            self._frontiers[key.canonical] = OnlyStreamingStreamFrontier(
                key,
                OnlyTimestamp.from_unix_nanos(int(raw["last_closed_bar_start_ns"])),
                OnlyTimestamp.from_unix_nanos(int(raw["last_closed_bar_end_ns"])),
                OnlyMarketDataUpdateId(str(raw["last_update_id"])),
                int(raw["canonical_sequence"]),
                None if raw["provider_sequence"] is None else int(raw["provider_sequence"]),
                int(raw["processed_count"]),
            )
        self._recent = deque((str(item[0]), int(item[1])) for item in raw_recent)
        self._recent_set = set(self._recent)


__all__ = [
    "OnlyStreamingContinuityTracker",
    "OnlyStreamingStreamFrontier",
    "OnlyStreamingStreamKey",
]
