from decimal import Decimal

from onlyalpha.factor.base import OnlyTimeSeriesFactor
from onlyalpha.factor.context import OnlyFactorBarContext
from onlyalpha.factor.score import (
    OnlyFactorQualityFlag,
    OnlyFactorScore,
    OnlyFactorScoreDimension,
)
from onlyalpha.indicator.macd import OnlyMacdCrossState, OnlyMacdSnapshot

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
