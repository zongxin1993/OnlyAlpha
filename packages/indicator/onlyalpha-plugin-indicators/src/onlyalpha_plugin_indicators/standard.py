"""Characterization-preserving Decimal rolling Indicator backends."""
# ruff: noqa: E701, E702

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal, localcontext

from onlyalpha.calculation.definition import OnlyCalculationDefinition
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.indicator.base import OnlyBarIndicator
from onlyalpha.indicator.identifiers import OnlyIndicatorId, OnlyIndicatorTypeId
from onlyalpha.indicator.score import OnlyIndicatorQualityFlag, OnlyIndicatorScore, OnlyIndicatorScoreDimension
from onlyalpha.indicator.snapshot import OnlyIndicatorSnapshot, OnlyWarmupProgress
from onlyalpha.plugin.capabilities import OnlyCheckpointCapability
from onlyalpha_plugin_indicators.snapshots import (
    OnlyAtrSnapshot,
    OnlyBollingerSnapshot,
    OnlyRsiSnapshot,
    OnlyRsiZone,
    OnlyScalarIndicatorSnapshot,
)


@dataclass(frozen=True, slots=True)
class OnlyRollingIndicatorConfig:
    indicator_id: OnlyIndicatorId
    bar_type: OnlyBarType
    period: int
    price_field: str = "CLOSE"
    standard_deviations: Decimal = Decimal("2")

    def __post_init__(self) -> None:
        if self.period <= 0:
            raise ValueError("indicator period must be positive")
        if self.price_field.upper() not in {"CLOSE", "VOLUME"}:
            raise ValueError("price_field must be CLOSE or VOLUME")
        if self.standard_deviations <= 0:
            raise ValueError("standard_deviations must be positive")
        object.__setattr__(self, "price_field", self.price_field.upper())


class OnlyStandardBarIndicator(OnlyBarIndicator[OnlyIndicatorSnapshot]):
    _Q = Decimal("0.000000000001")

    def __init__(self, config: OnlyRollingIndicatorConfig, indicator_type: OnlyIndicatorTypeId) -> None:
        self.config, self._type = config, indicator_type
        self._definition: OnlyCalculationDefinition | None = None
        self.reset()

    @property
    def definition(self) -> OnlyCalculationDefinition:
        if self._definition is None:
            raise RuntimeError("Indicator definition was not bound by composition")
        return self._definition

    def bind_definition(self, definition: OnlyCalculationDefinition) -> None:
        self._definition = definition

    @property
    def indicator_id(self) -> OnlyIndicatorId:
        return self.config.indicator_id

    @property
    def indicator_type(self) -> OnlyIndicatorTypeId:
        return self._type

    @property
    def bar_type(self) -> OnlyBarType:
        return self.config.bar_type

    @property
    def ready(self) -> bool:
        return self._snapshot.ready

    @property
    def warmup_progress(self) -> OnlyWarmupProgress:
        return OnlyWarmupProgress(self._samples, self.config.period)

    def reset(self) -> None:
        self._values: deque[Decimal] = deque(maxlen=self.config.period + 1)
        self._true_ranges: deque[Decimal] = deque(maxlen=self.config.period)
        self._samples = 0
        self._last_event_ns: int | None = None
        self._previous_close: Decimal | None = None
        self._ema: Decimal | None = None
        self._snapshot: OnlyIndicatorSnapshot = OnlyScalarIndicatorSnapshot(self.indicator_id, None, 0, None, False)

    def snapshot(self) -> OnlyIndicatorSnapshot:
        return self._snapshot

    def update_bar(self, bar: OnlyBar) -> None:
        if not bar.is_closed:
            raise ValueError(f"{self._type} accepts closed Bars only")
        event_ns = OnlyTimestamp.from_datetime(bar.ts_event).unix_nanos
        if self._last_event_ns is not None:
            if event_ns < self._last_event_ns:
                raise ValueError(f"{self._type} cannot apply an out-of-order Bar")
            if event_ns == self._last_event_ns:
                return
        value = bar.close.value if self.config.price_field == "CLOSE" else bar.volume.value
        self._values.append(value)
        self._samples += 1
        self._last_event_ns = event_ns
        timestamp = OnlyTimestamp.from_unix_nanos(event_ns)
        kind = str(self._type)
        if kind == "EMA":
            alpha = Decimal(2) / Decimal(self.config.period + 1)
            self._ema = value if self._ema is None else self._ema + alpha * (value - self._ema)
            self._snapshot = OnlyScalarIndicatorSnapshot(
                self.indicator_id, timestamp, self._samples, self._q(self._ema), self.warmup_progress.ready
            )
        elif kind == "SMA":
            self._snapshot = self._scalar(timestamp, self._mean(tuple(self._values)[-self.config.period :]))
        elif kind == "RSI":
            self._snapshot = self._rsi(timestamp)
        elif kind == "ATR":
            previous = self._previous_close
            true_range = bar.high.value - bar.low.value
            if previous is not None:
                true_range = max(true_range, abs(bar.high.value - previous), abs(bar.low.value - previous))
            self._true_ranges.append(true_range)
            atr = self._mean(tuple(self._true_ranges)) if self._true_ranges else None
            ready = len(self._true_ranges) >= self.config.period
            normalized = None if atr is None or bar.close.value == 0 else self._q(atr / bar.close.value)
            self._snapshot = OnlyAtrSnapshot(
                self.indicator_id, timestamp, self._samples, self._q(atr), normalized, ready
            )
        elif kind == "BOLLINGER":
            values = tuple(self._values)[-self.config.period :]
            ready = len(values) >= self.config.period
            mean = self._mean(values)
            deviation = self._std(values, mean)
            width = deviation * self.config.standard_deviations
            self._snapshot = OnlyBollingerSnapshot(
                self.indicator_id,
                timestamp,
                self._samples,
                self._q(mean),
                self._q(mean + width),
                self._q(mean - width),
                ready,
            )
        elif kind == "ROLLING_RETURN":
            values = tuple(self._values)
            result = (
                None
                if len(values) <= self.config.period or values[-self.config.period - 1] == 0
                else values[-1] / values[-self.config.period - 1] - 1
            )
            self._snapshot = self._scalar(timestamp, result)
        elif kind == "ROLLING_VOLATILITY":
            values = tuple(self._values)[-self.config.period :]
            self._snapshot = self._scalar(timestamp, self._std(values, self._mean(values)))
        elif kind == "ZSCORE":
            values = tuple(self._values)[-self.config.period :]
            mean = self._mean(values)
            std = self._std(values, mean)
            self._snapshot = self._scalar(timestamp, Decimal(0) if std == 0 else (value - mean) / std)
        else:
            raise ValueError(f"unsupported built-in indicator: {kind}")
        self._previous_close = bar.close.value

    def canonical_score(self) -> OnlyIndicatorScore | None:
        dimension = OnlyIndicatorScoreDimension.CUSTOM
        if isinstance(self._snapshot, OnlyScalarIndicatorSnapshot):
            raw = self._snapshot.value
        elif isinstance(self._snapshot, OnlyAtrSnapshot):
            raw = self._snapshot.normalized_atr
            dimension = OnlyIndicatorScoreDimension.VOLATILITY
        else:
            raw = None
        if raw is None:
            return None
        if str(self._type) == "RSI":
            raw = (raw - Decimal(50)) / Decimal(50)
            dimension = OnlyIndicatorScoreDimension.POSITION
        elif str(self._type) in {"ROLLING_RETURN", "ZSCORE"}:
            dimension = OnlyIndicatorScoreDimension.MOMENTUM
        flags = frozenset() if self.ready else frozenset({OnlyIndicatorQualityFlag.WARMING_UP})
        return OnlyIndicatorScore(
            self.indicator_id,
            dimension,
            max(Decimal("-1"), min(Decimal("1"), raw)),
            Decimal(min(self._samples, self.config.period)) / Decimal(self.config.period),
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
            "ema": None if self._ema is None else str(self._ema),
            "last_event_ns": self._last_event_ns,
            "previous_close": None if self._previous_close is None else str(self._previous_close),
            "samples": self._samples,
            "snapshot": dict(self._snapshot.to_dict()),
            "snapshot_type": type(self._snapshot).__name__,
            "true_ranges": [str(x) for x in self._true_ranges],
            "values": [str(x) for x in self._values],
        }

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, dict):
            raise ValueError("standard Indicator checkpoint must be an object")
        self._values = deque((Decimal(str(x)) for x in payload["values"]), maxlen=self.config.period + 1)
        self._true_ranges = deque((Decimal(str(x)) for x in payload["true_ranges"]), maxlen=self.config.period)
        self._samples = int(payload["samples"])
        self._last_event_ns = None if payload["last_event_ns"] is None else int(payload["last_event_ns"])
        self._previous_close = None if payload["previous_close"] is None else Decimal(str(payload["previous_close"]))
        self._ema = None if payload["ema"] is None else Decimal(str(payload["ema"]))
        snapshot = payload["snapshot"]
        if not isinstance(snapshot, dict):
            raise ValueError("standard Indicator checkpoint snapshot must be an object")
        timestamp = snapshot["ts_event_ns"]
        common = (
            OnlyIndicatorId(str(snapshot["indicator_id"])),
            None if timestamp is None else OnlyTimestamp.from_unix_nanos(int(timestamp)),
            int(snapshot["samples"]),
        )
        kind = str(payload["snapshot_type"])
        if kind == "OnlyAtrSnapshot":
            self._snapshot = OnlyAtrSnapshot(
                *common,
                None if snapshot["atr"] is None else Decimal(str(snapshot["atr"])),
                None if snapshot["normalized_atr"] is None else Decimal(str(snapshot["normalized_atr"])),
                bool(snapshot["ready"]),
            )
        elif kind == "OnlyBollingerSnapshot":
            self._snapshot = OnlyBollingerSnapshot(
                *common,
                None if snapshot["middle"] is None else Decimal(str(snapshot["middle"])),
                None if snapshot["upper"] is None else Decimal(str(snapshot["upper"])),
                None if snapshot["lower"] is None else Decimal(str(snapshot["lower"])),
                bool(snapshot["ready"]),
            )
        else:
            scalar = (
                *common,
                None if snapshot["value"] is None else Decimal(str(snapshot["value"])),
                bool(snapshot["ready"]),
            )
            if kind == "OnlyRsiSnapshot":
                self._snapshot = OnlyRsiSnapshot(*scalar, OnlyRsiZone(str(snapshot["zone"])))
            elif kind == "OnlyScalarIndicatorSnapshot":
                self._snapshot = OnlyScalarIndicatorSnapshot(*scalar)
            else:
                raise ValueError(f"standard Indicator checkpoint snapshot type is unsupported: {kind}")

    def _scalar(self, timestamp: OnlyTimestamp, value: Decimal | None) -> OnlyScalarIndicatorSnapshot:
        return OnlyScalarIndicatorSnapshot(
            self.indicator_id, timestamp, self._samples, self._q(value), self._samples >= self.config.period
        )

    def _rsi(self, timestamp: OnlyTimestamp) -> OnlyRsiSnapshot:
        values = tuple(self._values)
        rsi = None
        if len(values) >= 2:
            changes = tuple(right - left for left, right in zip(values, values[1:], strict=False))[
                -self.config.period :
            ]
            gain = sum((max(x, Decimal(0)) for x in changes), Decimal(0)) / Decimal(len(changes))
            loss = sum((max(-x, Decimal(0)) for x in changes), Decimal(0)) / Decimal(len(changes))
            rsi = Decimal(100) if loss == 0 else Decimal(100) - Decimal(100) / (Decimal(1) + gain / loss)
        zone = (
            OnlyRsiZone.NEUTRAL
            if rsi is None or Decimal(30) <= rsi <= Decimal(70)
            else (OnlyRsiZone.OVERSOLD if rsi < 30 else OnlyRsiZone.OVERBOUGHT)
        )
        return OnlyRsiSnapshot(
            self.indicator_id, timestamp, self._samples, self._q(rsi), self._samples >= self.config.period, zone
        )

    @classmethod
    def _mean(cls, values: tuple[Decimal, ...]) -> Decimal:
        return Decimal(0) if not values else sum(values, Decimal(0)) / Decimal(len(values))

    @classmethod
    def _std(cls, values: tuple[Decimal, ...], mean: Decimal) -> Decimal:
        if not values:
            return Decimal(0)
        with localcontext() as context:
            context.prec = 28
            return (sum(((x - mean) ** 2 for x in values), Decimal(0)) / Decimal(len(values))).sqrt()

    @classmethod
    def _q(cls, value: Decimal | None) -> Decimal | None:
        return None if value is None else value.quantize(cls._Q)
