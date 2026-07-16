from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.factor.identifiers import OnlyFactorId


class OnlyFactorScoreDimension(StrEnum):
    ALPHA = "ALPHA"
    DIRECTION = "DIRECTION"
    MOMENTUM = "MOMENTUM"
    VALUE = "VALUE"
    QUALITY = "QUALITY"
    VOLATILITY = "VOLATILITY"
    LIQUIDITY = "LIQUIDITY"
    RISK = "RISK"
    CUSTOM = "CUSTOM"


class OnlyFactorQualityFlag(StrEnum):
    WARMING_UP = "WARMING_UP"
    MISSING_INPUT = "MISSING_INPUT"
    MISSING_ASSET = "MISSING_ASSET"
    STALE = "STALE"


@dataclass(frozen=True, slots=True)
class OnlyFactorScore:
    factor_id: OnlyFactorId
    value: Decimal
    dimension: OnlyFactorScoreDimension
    confidence: Decimal
    ready: bool
    ts_event: OnlyTimestamp | None
    quality_flags: frozenset[OnlyFactorQualityFlag] = frozenset()

    def __post_init__(self) -> None:
        if not Decimal("-1") <= self.value <= Decimal("1"):
            raise ValueError("factor score value must be in [-1, 1]")
        if not Decimal("0") <= self.confidence <= Decimal("1"):
            raise ValueError("factor score confidence must be in [0, 1]")
