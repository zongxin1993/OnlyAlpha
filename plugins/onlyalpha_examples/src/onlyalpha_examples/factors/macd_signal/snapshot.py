from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.factor.identifiers import OnlyFactorId
from onlyalpha.factor.snapshot import OnlyFactorSnapshot
from onlyalpha.indicator.macd import OnlyMacdSnapshot


@dataclass(frozen=True, slots=True)
class OnlyMacdSignalFactorSnapshot(OnlyFactorSnapshot):
    factor_id: OnlyFactorId
    ts_event: OnlyTimestamp | None
    ready: bool
    signal: str
    trend_score: Decimal
    confidence: Decimal
    macd_snapshot: OnlyMacdSnapshot

    def to_dict(self) -> Mapping[str, object]:
        return {
            "factor_id": str(self.factor_id),
            "ts_event_ns": None if self.ts_event is None else self.ts_event.unix_nanos,
            "ready": self.ready,
            "signal": self.signal,
            "trend_score": str(self.trend_score),
            "confidence": str(self.confidence),
            "macd": dict(self.macd_snapshot.to_dict()),
        }
