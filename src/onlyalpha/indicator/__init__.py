"""Minimal synchronous indicator preparation interfaces."""

from onlyalpha.indicator.base import (
    OnlyIndicator,
    OnlyIndicatorId,
    OnlyIndicatorRegistration,
    OnlyIndicatorRequirement,
    OnlyIndicatorValue,
)
from onlyalpha.indicator.pipeline import OnlyIndicatorPipeline

__all__ = [
    "OnlyIndicator",
    "OnlyIndicatorId",
    "OnlyIndicatorPipeline",
    "OnlyIndicatorRegistration",
    "OnlyIndicatorRequirement",
    "OnlyIndicatorValue",
]
