from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from onlyalpha.domain.market import OnlyBarType
from onlyalpha.indicator.identifiers import OnlyIndicatorId


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

    @classmethod
    def from_mapping(
        cls,
        indicator_id: OnlyIndicatorId,
        bar_type: OnlyBarType,
        parameters: Mapping[str, object],
    ) -> OnlyMacdIndicatorConfig:
        fast = int(str(parameters.get("fast_period", 12)))
        slow = int(str(parameters.get("slow_period", 26)))
        signal = int(str(parameters.get("signal_period", 9)))
        warmup_raw = parameters.get("warmup_bars")
        return cls(
            indicator_id,
            bar_type,
            fast,
            slow,
            signal,
            str(parameters.get("price_field", "CLOSE")),
            None if warmup_raw is None else int(str(warmup_raw)),
        )
