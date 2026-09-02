"""Immutable output DTOs for the official Indicator semantics."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.indicator.identifiers import OnlyIndicatorId
from onlyalpha.indicator.snapshot import OnlyIndicatorSnapshot


@dataclass(frozen=True, slots=True)
class OnlyScalarIndicatorSnapshot(OnlyIndicatorSnapshot):
    indicator_id: OnlyIndicatorId
    ts_event: OnlyTimestamp | None
    samples: int
    value: Decimal | None
    ready: bool

    def to_dict(self) -> Mapping[str, object]:
        return {
            "indicator_id": str(self.indicator_id),
            "ts_event_ns": None if self.ts_event is None else self.ts_event.unix_nanos,
            "samples": self.samples,
            "value": None if self.value is None else str(self.value),
            "ready": self.ready,
        }


class OnlyRsiZone(StrEnum):
    OVERSOLD = "OVERSOLD"
    NEUTRAL = "NEUTRAL"
    OVERBOUGHT = "OVERBOUGHT"


@dataclass(frozen=True, slots=True)
class OnlyRsiSnapshot(OnlyScalarIndicatorSnapshot):
    zone: OnlyRsiZone = OnlyRsiZone.NEUTRAL


@dataclass(frozen=True, slots=True)
class OnlyAtrSnapshot(OnlyIndicatorSnapshot):
    indicator_id: OnlyIndicatorId
    ts_event: OnlyTimestamp | None
    samples: int
    atr: Decimal | None
    normalized_atr: Decimal | None
    ready: bool

    def to_dict(self) -> Mapping[str, object]:
        return {
            "indicator_id": str(self.indicator_id),
            "ts_event_ns": None if self.ts_event is None else self.ts_event.unix_nanos,
            "samples": self.samples,
            "atr": None if self.atr is None else str(self.atr),
            "normalized_atr": None if self.normalized_atr is None else str(self.normalized_atr),
            "ready": self.ready,
        }


@dataclass(frozen=True, slots=True)
class OnlyBollingerSnapshot(OnlyIndicatorSnapshot):
    indicator_id: OnlyIndicatorId
    ts_event: OnlyTimestamp | None
    samples: int
    middle: Decimal | None
    upper: Decimal | None
    lower: Decimal | None
    ready: bool

    def to_dict(self) -> Mapping[str, object]:
        return {
            "indicator_id": str(self.indicator_id),
            "ts_event_ns": None if self.ts_event is None else self.ts_event.unix_nanos,
            "samples": self.samples,
            "middle": None if self.middle is None else str(self.middle),
            "upper": None if self.upper is None else str(self.upper),
            "lower": None if self.lower is None else str(self.lower),
            "ready": self.ready,
        }


class OnlyMacdCrossState(StrEnum):
    NONE = "NONE"
    GOLDEN_CROSS = "GOLDEN_CROSS"
    DEATH_CROSS = "DEATH_CROSS"


@dataclass(frozen=True, slots=True)
class OnlyMacdSnapshot(OnlyIndicatorSnapshot):
    indicator_id: OnlyIndicatorId
    ts_event: OnlyTimestamp | None
    samples: int
    dif: Decimal
    dea: Decimal
    histogram: Decimal
    cross_state: OnlyMacdCrossState
    ready: bool

    def to_dict(self) -> Mapping[str, object]:
        return {
            "indicator_id": str(self.indicator_id),
            "ts_event_ns": None if self.ts_event is None else self.ts_event.unix_nanos,
            "samples": self.samples,
            "dif": str(self.dif),
            "dea": str(self.dea),
            "histogram": str(self.histogram),
            "cross_state": self.cross_state.value,
            "ready": self.ready,
        }

    @classmethod
    def empty(cls, indicator_id: OnlyIndicatorId) -> OnlyMacdSnapshot:
        return cls(indicator_id, None, 0, Decimal(0), Decimal(0), Decimal(0), OnlyMacdCrossState.NONE, False)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyMacdSnapshot:
        timestamp = payload.get("ts_event_ns")
        return cls(
            OnlyIndicatorId(str(payload["indicator_id"])),
            None if timestamp is None else OnlyTimestamp.from_unix_nanos(int(str(timestamp))),
            int(str(payload["samples"])),
            Decimal(str(payload["dif"])),
            Decimal(str(payload["dea"])),
            Decimal(str(payload["histogram"])),
            OnlyMacdCrossState(str(payload.get("cross_state", "NONE"))),
            bool(payload["ready"]),
        )
