"""Extensible indicator identifiers."""

from dataclasses import dataclass


@dataclass(frozen=True, order=True, slots=True)
class OnlyIndicatorId:
    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip()
        if not normalized:
            raise ValueError("indicator_id is required")
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, order=True, slots=True)
class OnlyIndicatorTypeId:
    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip()
        if not normalized:
            raise ValueError("indicator_type is required")
        if any(char.isspace() for char in normalized):
            raise ValueError("indicator_type cannot contain whitespace")
        object.__setattr__(self, "value", normalized.upper() if "." not in normalized else normalized.lower())

    def __str__(self) -> str:
        return self.value


MACD = OnlyIndicatorTypeId("MACD")
RSI = OnlyIndicatorTypeId("RSI")
EMA = OnlyIndicatorTypeId("EMA")
SMA = OnlyIndicatorTypeId("SMA")
ATR = OnlyIndicatorTypeId("ATR")
BOLLINGER = OnlyIndicatorTypeId("BOLLINGER")
ROLLING_RETURN = OnlyIndicatorTypeId("ROLLING_RETURN")
ROLLING_VOLATILITY = OnlyIndicatorTypeId("ROLLING_VOLATILITY")
ZSCORE = OnlyIndicatorTypeId("ZSCORE")
