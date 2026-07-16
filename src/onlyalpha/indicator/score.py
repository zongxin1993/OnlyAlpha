"""Dimension-aware optional canonical indicator scores."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.indicator.identifiers import OnlyIndicatorId


class OnlyIndicatorScoreDimension(StrEnum):
    DIRECTION = "DIRECTION"
    MOMENTUM = "MOMENTUM"
    POSITION = "POSITION"
    VOLATILITY = "VOLATILITY"
    LIQUIDITY = "LIQUIDITY"
    RISK = "RISK"
    QUALITY = "QUALITY"
    CUSTOM = "CUSTOM"


class OnlyIndicatorQualityFlag(StrEnum):
    WARMING_UP = "WARMING_UP"
    MISSING_INPUT = "MISSING_INPUT"
    STALE = "STALE"


@dataclass(frozen=True, slots=True)
class OnlyIndicatorScore:
    indicator_id: OnlyIndicatorId
    dimension: OnlyIndicatorScoreDimension
    value: Decimal
    confidence: Decimal
    ready: bool
    ts_event: OnlyTimestamp | None
    quality_flags: frozenset[OnlyIndicatorQualityFlag] = frozenset()

    def __post_init__(self) -> None:
        if not Decimal("-1") <= self.value <= Decimal("1"):
            raise ValueError("indicator score value must be in [-1, 1]")
        if not Decimal("0") <= self.confidence <= Decimal("1"):
            raise ValueError("indicator score confidence must be in [0, 1]")
