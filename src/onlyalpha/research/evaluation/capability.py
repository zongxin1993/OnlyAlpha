"""Single executable Statistics capability truth shared by admission and discovery."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.calculation import (
    FACTOR_SCORE_SEMANTIC_TYPE,
    FACTOR_VALUE_SEMANTIC_TYPE,
    TARGET_VALUE_SEMANTIC_TYPE,
    OnlyCalculationKind,
)

from .definition import OnlyResearchStatisticsMethod


@dataclass(frozen=True, slots=True)
class OnlyResearchStatisticsCapability:
    method: OnlyResearchStatisticsMethod
    variable_kinds: tuple[OnlyCalculationKind, ...]
    variable_semantic_types: tuple[str, ...]
    target_semantic_types: tuple[str, ...]
    target_required: bool = True
    executable: bool = True


_CAPABILITIES = tuple(
    OnlyResearchStatisticsCapability(
        method,
        (OnlyCalculationKind.FACTOR,),
        (FACTOR_SCORE_SEMANTIC_TYPE, FACTOR_VALUE_SEMANTIC_TYPE),
        (TARGET_VALUE_SEMANTIC_TYPE,),
    )
    for method in OnlyResearchStatisticsMethod
)


def only_research_statistics_capabilities() -> tuple[OnlyResearchStatisticsCapability, ...]:
    return _CAPABILITIES


def only_research_statistics_capability(
    method: OnlyResearchStatisticsMethod,
) -> OnlyResearchStatisticsCapability:
    return next(item for item in _CAPABILITIES if item.method is method)


__all__ = [
    "OnlyResearchStatisticsCapability",
    "only_research_statistics_capabilities",
    "only_research_statistics_capability",
]
