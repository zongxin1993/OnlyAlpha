from decimal import Decimal

from onlyalpha_plugin_indicators import OnlyMacdCrossState, OnlyMacdSnapshot

from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.factor.base import OnlyTimeSeriesFactor
from onlyalpha.factor.context import OnlyFactorBarContext
from onlyalpha.factor.identifiers import OnlyFactorId
from onlyalpha.factor.score import (
    OnlyFactorQualityFlag,
    OnlyFactorScore,
    OnlyFactorScoreDimension,
)
from onlyalpha.plugin.api import OnlyCheckpointCapability

from .config import OnlyMacdSignalFactorConfig
from .snapshot import OnlyMacdSignalFactorSnapshot


class OnlyMacdSignalFactor(OnlyTimeSeriesFactor):
    def __init__(self, config: OnlyMacdSignalFactorConfig) -> None:
        super().__init__(config)
        self.config = config
        self._indicator_id = config.indicators[0].indicator_id
        self._snapshot = OnlyMacdSignalFactorSnapshot(
            config.factor_id,
            None,
            False,
            "WARMING_UP",
            Decimal(0),
            Decimal(0),
            OnlyMacdSnapshot.empty(self._indicator_id),
        )
        self._trace: list[OnlyMacdSignalFactorSnapshot] = []

    @property
    def trace(self) -> tuple[OnlyMacdSignalFactorSnapshot, ...]:
        return tuple(self._trace)

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
        self._snapshot = OnlyMacdSignalFactorSnapshot(
            self.factor_id,
            macd.ts_event,
            macd.ready,
            signal,
            score,
            confidence,
            macd,
        )
        self._trace.append(self._snapshot)

    def snapshot(self) -> OnlyMacdSignalFactorSnapshot:
        return self._snapshot

    def score(self) -> OnlyFactorScore:
        flags = frozenset() if self.ready else frozenset({OnlyFactorQualityFlag.WARMING_UP})
        return OnlyFactorScore(
            self.factor_id,
            self._snapshot.trend_score,
            OnlyFactorScoreDimension.MOMENTUM,
            self._snapshot.confidence,
            self.ready,
            self._snapshot.ts_event,
            flags,
        )

    @property
    def checkpoint_schema_version(self) -> int | None:
        return 1

    @property
    def checkpoint_capability(self) -> OnlyCheckpointCapability | None:
        return OnlyCheckpointCapability.CHECKPOINTABLE

    def capture_checkpoint(self) -> object:
        return {
            "snapshot": dict(self._snapshot.to_dict()),
            "trace": [dict(item.to_dict()) for item in self._trace],
        }

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, dict):
            raise ValueError("MACD Factor checkpoint must be an object")

        def decode(value: object) -> OnlyMacdSignalFactorSnapshot:
            if not isinstance(value, dict):
                raise ValueError("MACD Factor snapshot checkpoint must be an object")
            event = value["ts_event_ns"]
            macd = value["macd"]
            if not isinstance(macd, dict):
                raise ValueError("MACD Factor indicator snapshot must be an object")
            return OnlyMacdSignalFactorSnapshot(
                OnlyFactorId(str(value["factor_id"])),
                None if event is None else OnlyTimestamp.from_unix_nanos(int(event)),
                bool(value["ready"]),
                str(value["signal"]),
                Decimal(str(value["trend_score"])),
                Decimal(str(value["confidence"])),
                OnlyMacdSnapshot.from_dict(macd),
            )

        self._snapshot = decode(payload["snapshot"])
        self._trace = [decode(item) for item in payload["trace"]]
