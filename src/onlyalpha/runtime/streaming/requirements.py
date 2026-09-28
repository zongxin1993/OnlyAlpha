"""Composition of independent Runtime market-data requirements."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.domain.market import OnlyBarType, OnlyTradeInputType
from onlyalpha.market_data.resolution import OnlyMarketDataConstructionGraph
from onlyalpha.plugin.capabilities import OnlyDataSourceCapabilities


@dataclass(frozen=True, slots=True)
class OnlyRuntimeMarketDataRequirement:
    authority: str
    data_types: frozenset[OnlyMarketDataType]
    bar_types: frozenset[OnlyBarType] = frozenset()

    def __post_init__(self) -> None:
        if not self.authority.strip() or not self.data_types:
            raise ValueError("RUNTIME_MARKET_DATA_REQUIREMENT_INVALID")
        if bool(self.bar_types) != (OnlyMarketDataType.BAR in self.data_types):
            raise ValueError("RUNTIME_MARKET_DATA_BAR_REQUIREMENT_INVALID")


@dataclass(frozen=True, slots=True)
class OnlyRuntimeMarketDataRequirementPlan:
    requirements: tuple[OnlyRuntimeMarketDataRequirement, ...]
    data_types: frozenset[OnlyMarketDataType]
    bar_types: frozenset[OnlyBarType]


def only_compose_runtime_market_data_requirements(
    *requirements: OnlyRuntimeMarketDataRequirement,
) -> OnlyRuntimeMarketDataRequirementPlan:
    if not requirements:
        raise ValueError("RUNTIME_MARKET_DATA_REQUIREMENTS_EMPTY")
    ordered = tuple(sorted(requirements, key=lambda item: item.authority))
    if len({item.authority for item in ordered}) != len(ordered):
        raise ValueError("RUNTIME_MARKET_DATA_REQUIREMENT_AUTHORITY_DUPLICATE")
    return OnlyRuntimeMarketDataRequirementPlan(
        ordered,
        frozenset(kind for item in ordered for kind in item.data_types),
        frozenset(bar_type for item in ordered for bar_type in item.bar_types),
    )


def only_project_construction_provider_requirement(
    graph: OnlyMarketDataConstructionGraph,
    *,
    authority: str = "STRATEGY_REVISION",
) -> OnlyRuntimeMarketDataRequirement:
    data_types = frozenset(
        OnlyMarketDataType.TRADE if isinstance(item, OnlyTradeInputType) else OnlyMarketDataType.BAR
        for item in graph.provider_inputs
    )
    if not data_types:
        raise ValueError("CONSTRUCTION_PROVIDER_INPUTS_EMPTY")
    return OnlyRuntimeMarketDataRequirement(
        authority,
        data_types,
        frozenset(item for item in graph.provider_inputs if isinstance(item, OnlyBarType)),
    )


def only_project_data_source_capabilities(
    plan: OnlyRuntimeMarketDataRequirementPlan,
    *,
    historical: bool = False,
    live: bool = False,
    live_reconnect: bool = False,
) -> OnlyDataSourceCapabilities:
    """Project exact provider families without merging independent time horizons."""

    bars = OnlyMarketDataType.BAR in plan.data_types
    trades = OnlyMarketDataType.TRADE in plan.data_types
    return OnlyDataSourceCapabilities(
        historical_bars=historical and bars,
        historical_ticks=historical and trades,
        live_bars=live and bars,
        live_ticks=live and trades,
        live_reconnect=live_reconnect,
    )


__all__ = [name for name in globals() if name.startswith(("Only", "only_"))]
