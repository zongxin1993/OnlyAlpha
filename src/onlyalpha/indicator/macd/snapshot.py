from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.indicator.identifiers import OnlyIndicatorId
from onlyalpha.indicator.snapshot import OnlyIndicatorSnapshot


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
        event = payload.get("ts_event_ns")
        return cls(
            OnlyIndicatorId(str(payload["indicator_id"])),
            None if event is None else OnlyTimestamp.from_unix_nanos(int(str(event))),
            int(str(payload["samples"])),
            Decimal(str(payload["dif"])),
            Decimal(str(payload["dea"])),
            Decimal(str(payload["histogram"])),
            OnlyMacdCrossState(str(payload.get("cross_state", "NONE"))),
            bool(payload["ready"]),
        )
