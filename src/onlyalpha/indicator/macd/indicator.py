"""Deterministic Decimal MACD updated only from closed Bars."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.indicator.base import OnlyIndicator, OnlyIndicatorId, OnlyIndicatorValue, OnlyStructuredIndicatorValue


@dataclass(frozen=True, slots=True)
class OnlyMacdIndicatorConfig:
    indicator_id: OnlyIndicatorId
    bar_type: OnlyBarType
    fast_period: int = 12
    slow_period: int = 26
    signal_period: int = 9
    price_field: str = "close"
    warmup_bars: int | None = None

    def __post_init__(self) -> None:
        if min(self.fast_period, self.slow_period, self.signal_period) <= 0:
            raise ValueError("MACD periods must be positive")
        if self.fast_period >= self.slow_period:
            raise ValueError("MACD fast_period must be less than slow_period")
        if self.price_field != "close":
            raise ValueError("first-phase MACD supports the closed Bar close field only")
        warmup = self.slow_period + self.signal_period - 1 if self.warmup_bars is None else self.warmup_bars
        if warmup < self.slow_period:
            raise ValueError("MACD warmup_bars cannot be less than slow_period")
        object.__setattr__(self, "warmup_bars", warmup)


@dataclass(frozen=True, slots=True)
class OnlyMacdSnapshot(OnlyStructuredIndicatorValue):
    indicator_id: OnlyIndicatorId
    ts_event: OnlyTimestamp
    samples: int
    dif: Decimal
    dea: Decimal
    histogram: Decimal
    ready: bool

    @property
    def value_type(self) -> str:
        return "MACD"

    def to_dict(self) -> Mapping[str, object]:
        return {
            "indicator_id": str(self.indicator_id),
            "ts_event_ns": self.ts_event.unix_nanos,
            "samples": self.samples,
            "dif": str(self.dif),
            "dea": str(self.dea),
            "histogram": str(self.histogram),
            "ready": self.ready,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyMacdSnapshot:
        return cls(
            OnlyIndicatorId(str(payload["indicator_id"])),
            OnlyTimestamp.from_unix_nanos(int(str(payload["ts_event_ns"]))),
            int(str(payload["samples"])),
            Decimal(str(payload["dif"])),
            Decimal(str(payload["dea"])),
            Decimal(str(payload["histogram"])),
            bool(payload["ready"]),
        )


class OnlyMacdIndicator(OnlyIndicator):
    """Incremental EMA MACD with no access to future history."""

    _QUANTUM = Decimal("0.000000000001")

    def __init__(self, config: OnlyMacdIndicatorConfig) -> None:
        self.config = config
        self._fast: Decimal | None = None
        self._slow: Decimal | None = None
        self._dea: Decimal | None = None
        self._samples = 0
        self._last_event_ns: int | None = None
        self._snapshot: OnlyMacdSnapshot | None = None

    @property
    def indicator_id(self) -> OnlyIndicatorId:
        return self.config.indicator_id

    @property
    def bar_type(self) -> OnlyBarType:
        return self.config.bar_type

    @property
    def snapshot(self) -> OnlyMacdSnapshot | None:
        return self._snapshot

    def update(self, bar: OnlyBar, history: tuple[OnlyBar, ...]) -> OnlyIndicatorValue:
        del history
        if not bar.is_closed:
            raise ValueError("MACD accepts closed Bars only")
        event_ns = OnlyTimestamp.from_datetime(bar.ts_event).unix_nanos
        if self._last_event_ns is not None:
            if event_ns < self._last_event_ns:
                raise ValueError("MACD cannot apply an out-of-order Bar")
            if event_ns == self._last_event_ns:
                if self._snapshot is None:
                    raise RuntimeError("MACD duplicate state is unavailable")
                return self._snapshot
        price = bar.close.value
        fast_alpha = Decimal(2) / Decimal(self.config.fast_period + 1)
        slow_alpha = Decimal(2) / Decimal(self.config.slow_period + 1)
        signal_alpha = Decimal(2) / Decimal(self.config.signal_period + 1)
        self._fast = price if self._fast is None else self._ema(self._fast, price, fast_alpha)
        self._slow = price if self._slow is None else self._ema(self._slow, price, slow_alpha)
        dif = (self._fast - self._slow).quantize(self._QUANTUM)
        self._dea = dif if self._dea is None else self._ema(self._dea, dif, signal_alpha)
        dea = self._dea.quantize(self._QUANTUM)
        self._samples += 1
        self._last_event_ns = event_ns
        self._snapshot = OnlyMacdSnapshot(
            self.indicator_id,
            OnlyTimestamp.from_unix_nanos(event_ns),
            self._samples,
            dif,
            dea,
            ((dif - dea) * Decimal(2)).quantize(self._QUANTUM),
            self._samples >= int(self.config.warmup_bars or 0),
        )
        return self._snapshot

    @classmethod
    def _ema(cls, previous: Decimal, value: Decimal, alpha: Decimal) -> Decimal:
        return (previous + alpha * (value - previous)).quantize(cls._QUANTUM)
