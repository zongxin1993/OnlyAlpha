"""Characterization-preserving MACD trading backend."""
# ruff: noqa: E702

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.calculation.definition import OnlyCalculationDefinition
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.indicator.base import OnlyBarIndicator
from onlyalpha.indicator.identifiers import MACD, OnlyIndicatorId, OnlyIndicatorTypeId
from onlyalpha.indicator.score import OnlyIndicatorQualityFlag, OnlyIndicatorScore, OnlyIndicatorScoreDimension
from onlyalpha.indicator.snapshot import OnlyWarmupProgress
from onlyalpha.plugin.capabilities import OnlyCheckpointCapability
from onlyalpha_plugin_indicators.snapshots import OnlyMacdCrossState, OnlyMacdSnapshot


@dataclass(frozen=True, slots=True)
class OnlyMacdIndicatorConfig:
    indicator_id: OnlyIndicatorId
    bar_type: OnlyBarType
    fast_period: int = 12
    slow_period: int = 26
    signal_period: int = 9
    price_field: str = "CLOSE"
    warmup_bars: int | None = None

    def __post_init__(self) -> None:
        if min(self.fast_period, self.slow_period, self.signal_period) <= 0:
            raise ValueError("MACD periods must be positive")
        if self.fast_period >= self.slow_period:
            raise ValueError("MACD fast_period must be less than slow_period")
        if self.price_field.upper() != "CLOSE":
            raise ValueError("MACD supports CLOSE price only")
        warmup = self.slow_period + self.signal_period - 1 if self.warmup_bars is None else self.warmup_bars
        if warmup < self.slow_period:
            raise ValueError("MACD warmup_bars cannot be less than slow_period")
        object.__setattr__(self, "price_field", "CLOSE")
        object.__setattr__(self, "warmup_bars", warmup)


class OnlyMacdIndicator(OnlyBarIndicator[OnlyMacdSnapshot]):
    _QUANTUM = Decimal("0.000000000001")

    def __init__(self, config: OnlyMacdIndicatorConfig, definition: OnlyCalculationDefinition | None = None) -> None:
        self.config = config
        if definition is None:
            from onlyalpha_plugin_indicators.registration import TYPES, resolve_definition

            definition = resolve_definition(
                TYPES[-1],
                {
                    "fast_period": config.fast_period,
                    "slow_period": config.slow_period,
                    "signal_period": config.signal_period,
                    "price_field": config.price_field,
                    "warmup_bars": config.warmup_bars,
                },
            )
        self._definition = definition
        self.reset()

    @property
    def definition(self) -> OnlyCalculationDefinition:
        return self._definition

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
        required = int(self.config.warmup_bars or 1)
        flags = frozenset() if self.ready else frozenset({OnlyIndicatorQualityFlag.WARMING_UP})
        return OnlyIndicatorScore(
            self.indicator_id,
            OnlyIndicatorScoreDimension.MOMENTUM,
            value,
            Decimal(min(self._samples, required)) / Decimal(required),
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
            "dea": None if self._dea is None else str(self._dea),
            "fast": None if self._fast is None else str(self._fast),
            "last_event_ns": self._last_event_ns,
            "samples": self._samples,
            "slow": None if self._slow is None else str(self._slow),
            "snapshot": dict(self._snapshot.to_dict()),
        }

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, dict):
            raise ValueError("MACD checkpoint must be an object")
        self._fast = None if payload["fast"] is None else Decimal(str(payload["fast"]))
        self._slow = None if payload["slow"] is None else Decimal(str(payload["slow"]))
        self._dea = None if payload["dea"] is None else Decimal(str(payload["dea"]))
        self._samples = int(payload["samples"])
        self._last_event_ns = None if payload["last_event_ns"] is None else int(payload["last_event_ns"])
        snapshot = payload["snapshot"]
        if not isinstance(snapshot, dict):
            raise ValueError("MACD checkpoint snapshot must be an object")
        self._snapshot = OnlyMacdSnapshot.from_dict(snapshot)

    @classmethod
    def _ema(cls, previous: Decimal, value: Decimal, alpha: Decimal) -> Decimal:
        return (previous + alpha * (value - previous)).quantize(cls._QUANTUM)


def config_from_parameters(
    indicator_id: OnlyIndicatorId, bar_type: OnlyBarType, parameters: Mapping[str, object]
) -> OnlyMacdIndicatorConfig:
    warmup = parameters.get("warmup_bars")
    return OnlyMacdIndicatorConfig(
        indicator_id,
        bar_type,
        int(str(parameters["fast_period"])),
        int(str(parameters["slow_period"])),
        int(str(parameters["signal_period"])),
        str(parameters["price_field"]),
        None if warmup is None else int(str(warmup)),
    )
