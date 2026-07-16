"""Deterministic Decimal MACD updated only from closed Bars."""

from decimal import Decimal

from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.indicator.base import OnlyBarIndicator
from onlyalpha.indicator.identifiers import MACD, OnlyIndicatorId, OnlyIndicatorTypeId
from onlyalpha.indicator.macd.config import OnlyMacdIndicatorConfig
from onlyalpha.indicator.macd.snapshot import OnlyMacdCrossState, OnlyMacdSnapshot
from onlyalpha.indicator.score import OnlyIndicatorQualityFlag, OnlyIndicatorScore, OnlyIndicatorScoreDimension
from onlyalpha.indicator.snapshot import OnlyWarmupProgress


class OnlyMacdIndicator(OnlyBarIndicator[OnlyMacdSnapshot]):
    _QUANTUM = Decimal("0.000000000001")

    def __init__(self, config: OnlyMacdIndicatorConfig) -> None:
        self.config = config
        self.reset()

    @property
    def indicator_id(self) -> OnlyIndicatorId:
        return self.config.indicator_id

    @property
    def indicator_type(self) -> OnlyIndicatorTypeId:
        return MACD

    @property
    def bar_type(self) -> OnlyBarType:
        return self.config.bar_type

    @property
    def ready(self) -> bool:
        return self._snapshot.ready

    @property
    def warmup_progress(self) -> OnlyWarmupProgress:
        return OnlyWarmupProgress(self._samples, int(self.config.warmup_bars or 1))

    def snapshot(self) -> OnlyMacdSnapshot:
        return self._snapshot

    def reset(self) -> None:
        self._fast: Decimal | None = None
        self._slow: Decimal | None = None
        self._dea: Decimal | None = None
        self._samples = 0
        self._last_event_ns: int | None = None
        self._snapshot = OnlyMacdSnapshot.empty(self.config.indicator_id)

    def update_bar(self, bar: OnlyBar) -> None:
        if not bar.is_closed:
            raise ValueError("MACD accepts closed Bars only")
        event_ns = OnlyTimestamp.from_datetime(bar.ts_event).unix_nanos
        if self._last_event_ns is not None:
            if event_ns < self._last_event_ns:
                raise ValueError("MACD cannot apply an out-of-order Bar")
            if event_ns == self._last_event_ns:
                return
        price = bar.close.value
        fast_alpha = Decimal(2) / Decimal(self.config.fast_period + 1)
        slow_alpha = Decimal(2) / Decimal(self.config.slow_period + 1)
        signal_alpha = Decimal(2) / Decimal(self.config.signal_period + 1)
        self._fast = price if self._fast is None else self._ema(self._fast, price, fast_alpha)
        self._slow = price if self._slow is None else self._ema(self._slow, price, slow_alpha)
        dif = (self._fast - self._slow).quantize(self._QUANTUM)
        previous_delta = self._snapshot.dif - self._snapshot.dea
        self._dea = dif if self._dea is None else self._ema(self._dea, dif, signal_alpha)
        dea = self._dea.quantize(self._QUANTUM)
        delta = dif - dea
        cross = OnlyMacdCrossState.NONE
        if self._samples > 0 and previous_delta <= 0 < delta:
            cross = OnlyMacdCrossState.GOLDEN_CROSS
        elif self._samples > 0 and previous_delta >= 0 > delta:
            cross = OnlyMacdCrossState.DEATH_CROSS
        self._samples += 1
        self._last_event_ns = event_ns
        self._snapshot = OnlyMacdSnapshot(
            self.indicator_id,
            OnlyTimestamp.from_unix_nanos(event_ns),
            self._samples,
            dif,
            dea,
            (delta * Decimal(2)).quantize(self._QUANTUM),
            cross,
            self.warmup_progress.ready,
        )

    def canonical_score(self) -> OnlyIndicatorScore:
        scale = abs(self._snapshot.dif) + abs(self._snapshot.dea) + Decimal("0.000000000001")
        value = max(Decimal("-1"), min(Decimal("1"), self._snapshot.histogram / scale))
        confidence = Decimal(min(self._samples, int(self.config.warmup_bars or 1))) / Decimal(
            int(self.config.warmup_bars or 1)
        )
        flags = frozenset() if self.ready else frozenset({OnlyIndicatorQualityFlag.WARMING_UP})
        return OnlyIndicatorScore(
            self.indicator_id,
            OnlyIndicatorScoreDimension.MOMENTUM,
            value,
            confidence,
            self.ready,
            self._snapshot.ts_event,
            flags,
        )

    @classmethod
    def _ema(cls, previous: Decimal, value: Decimal, alpha: Decimal) -> Decimal:
        return (previous + alpha * (value - previous)).quantize(cls._QUANTUM)
