"""Extensible indicator identifiers."""

from dataclasses import dataclass

from onlyalpha.calculation.definition import OnlyCalculationKind, OnlyCalculationTypeReference


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


_LEGACY_REFERENCES = {
    "MACD": "onlyalpha.indicator.macd",
    "RSI": "onlyalpha.indicator.rsi",
    "EMA": "onlyalpha.indicator.ema",
    "SMA": "onlyalpha.indicator.sma",
    "ATR": "onlyalpha.indicator.atr",
    "BOLLINGER": "onlyalpha.indicator.bollinger",
    "ROLLING_RETURN": "onlyalpha.indicator.rolling_return",
    "ROLLING_VOLATILITY": "onlyalpha.indicator.rolling_volatility",
    "ZSCORE": "onlyalpha.indicator.zscore",
}


def only_indicator_calculation_reference(indicator_type: OnlyIndicatorTypeId) -> OnlyCalculationTypeReference:
    """Normalize legacy product tokens through one fixed, non-latest mapping."""

    type_id = _LEGACY_REFERENCES.get(indicator_type.value, indicator_type.value)
    if type_id == indicator_type.value and "@" in type_id:
        type_id, semantic_version = type_id.rsplit("@", 1)
    elif type_id == indicator_type.value:
        raise ValueError("canonical indicator reference must include @semantic_version")
    else:
        semantic_version = "1"
    return OnlyCalculationTypeReference(OnlyCalculationKind.INDICATOR, type_id, semantic_version)
