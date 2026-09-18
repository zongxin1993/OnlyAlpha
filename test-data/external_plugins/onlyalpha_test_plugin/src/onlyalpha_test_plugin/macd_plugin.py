"""Installed test-only MACD Factor fixture for legacy configuration parsing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from onlyalpha_plugin_indicators import OnlyMacdCrossState, OnlyMacdSnapshot

from onlyalpha.calculation.definition import OnlyCalculationKind, OnlyCalculationTypeReference
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.factor.base import OnlyTimeSeriesFactor
from onlyalpha.factor.config import OnlyFactorConfig, OnlyFactorType, OnlyIndicatorSpec
from onlyalpha.factor.context import OnlyFactorBarContext
from onlyalpha.factor.identifiers import OnlyFactorId
from onlyalpha.factor.score import OnlyFactorQualityFlag, OnlyFactorScore, OnlyFactorScoreDimension
from onlyalpha.factor.snapshot import OnlyFactorSnapshot
from onlyalpha.plugin.api import OnlyCheckpointCapability


@dataclass(frozen=True, slots=True)
class OnlyTestMacdFactorSnapshot(OnlyFactorSnapshot):
    factor_id: OnlyFactorId
    ts_event: OnlyTimestamp | None
    ready: bool
    signal: str
    trend_score: Decimal
    confidence: Decimal
    macd_snapshot: OnlyMacdSnapshot

    def to_dict(self) -> Mapping[str, object]:
        timestamp = self.macd_snapshot.ts_event
        return {
            "factor_id": str(self.factor_id),
            "ts_event_ns": None if timestamp is None else timestamp.unix_nanos,
            "ready": self.ready,
            "signal": self.signal,
            "trend_score": str(self.trend_score),
            "confidence": str(self.confidence),
            "macd": dict(self.macd_snapshot.to_dict()),
        }


@dataclass(frozen=True, slots=True)
class OnlyTestMacdFactorConfig(OnlyFactorConfig):
    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> OnlyTestMacdFactorConfig:
        raw_specs = values.get("indicator_specs", ())
        if not isinstance(raw_specs, tuple) or len(raw_specs) != 1 or not isinstance(raw_specs[0], Mapping):
            raise ValueError("test MACD Factor requires one indicator")
        raw = raw_specs[0]
        return cls(
            values["factor_id"]
            if isinstance(values["factor_id"], OnlyFactorId)
            else OnlyFactorId(str(values["factor_id"])),
            OnlyFactorType(str(values["factor_type"])),
            (OnlyIndicatorSpec(raw["indicator_id"], raw["indicator_type"], raw["bar_type"], raw["parameters"]),),
            tuple(values.get("dependencies", ())),
            bool(values.get("required", True)),
            {},
        )


class OnlyTestMacdFactor(OnlyTimeSeriesFactor):
    calculation_reference = OnlyCalculationTypeReference(OnlyCalculationKind.FACTOR, "onlyalpha.test.factor.macd", "1")

    def __init__(self, config: OnlyTestMacdFactorConfig) -> None:
        super().__init__(config)
        self.config = config
        self._indicator_id = config.indicators[0].indicator_id
        self._snapshot = OnlyTestMacdFactorSnapshot(
            config.factor_id,
            None,
            False,
            "WARMING_UP",
            Decimal(0),
            Decimal(0),
            OnlyMacdSnapshot.empty(self._indicator_id),
        )

    def on_initialize(self) -> None:
        spec = self.config.indicators[0]
        self.context.indicators.create_for_bars(
            indicator_type=spec.indicator_type,
            indicator_id=spec.indicator_id,
            bar_type=spec.bar_type,
            parameters=spec.parameters,
        )

    def on_bar(self, context: OnlyFactorBarContext) -> None:
        del context
        macd = self.context.indicators.require_snapshot(self._indicator_id, OnlyMacdSnapshot)
        indicator_score = self.context.indicators.score(self._indicator_id)
        score = Decimal(0) if indicator_score is None else indicator_score.value
        confidence = Decimal(0) if indicator_score is None else indicator_score.confidence
        signal = {
            OnlyMacdCrossState.GOLDEN_CROSS: "GOLDEN_CROSS",
            OnlyMacdCrossState.DEATH_CROSS: "DEATH_CROSS",
        }.get(macd.cross_state, "HOLD" if macd.ready else "WARMING_UP")
        self._snapshot = OnlyTestMacdFactorSnapshot(
            self.factor_id,
            macd.ts_event,
            macd.ready,
            signal,
            score,
            confidence,
            macd,
        )

    def snapshot(self) -> OnlyTestMacdFactorSnapshot:
        return self._snapshot

    def score(self) -> OnlyFactorScore:
        flags = frozenset() if self.ready else frozenset({OnlyFactorQualityFlag.WARMING_UP})
        return OnlyFactorScore(
            self.factor_id,
            self._snapshot.trend_score,
            OnlyFactorScoreDimension.MOMENTUM,
            self._snapshot.confidence,
            self.ready,
            self._snapshot.macd_snapshot.ts_event,
            flags,
        )

    @property
    def checkpoint_schema_version(self) -> int | None:
        return 1

    @property
    def checkpoint_capability(self) -> OnlyCheckpointCapability | None:
        return OnlyCheckpointCapability.CHECKPOINTABLE

    def capture_checkpoint(self) -> object:
        return dict(self._snapshot.to_dict())

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, Mapping):
            raise ValueError("test MACD Factor checkpoint must be an object")
        event = payload["ts_event_ns"]
        macd = payload["macd"]
        if not isinstance(macd, Mapping):
            raise ValueError("test MACD Factor indicator checkpoint must be an object")
        self._snapshot = OnlyTestMacdFactorSnapshot(
            OnlyFactorId(str(payload["factor_id"])),
            None if event is None else OnlyTimestamp.from_unix_nanos(int(str(event))),
            bool(payload["ready"]),
            str(payload["signal"]),
            Decimal(str(payload["trend_score"])),
            Decimal(str(payload["confidence"])),
            OnlyMacdSnapshot.from_dict(macd),
        )
