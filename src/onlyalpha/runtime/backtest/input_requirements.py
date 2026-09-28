"""Separation of Strategy inputs from Trading Kernel economic inputs."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataVersion
from onlyalpha.data.models import (
    OnlyHistoricalBarRequest,
    OnlyHistoricalDataRange,
    OnlyHistoricalMarketDataInputPlan,
    OnlyHistoricalTradeRequest,
)
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.market import OnlyBarType, OnlyTradeInputType
from onlyalpha.domain.trading import OnlyReferencePriceKind
from onlyalpha.market.product import OnlyCompiledMarketPolicy
from onlyalpha.market_data.resolution import OnlyMarketDataConstructionGraph


@dataclass(frozen=True, slots=True)
class OnlyKernelEconomicInputRequirement:
    fact_family: OnlyMarketDataType
    reference_price_kind: OnlyReferencePriceKind | None = None


def only_kernel_economic_input_requirements(
    policy: OnlyCompiledMarketPolicy,
) -> tuple[OnlyKernelEconomicInputRequirement, ...]:
    """Derive Kernel-only data needs without changing Strategy Revision inputs."""

    requirements: set[tuple[OnlyMarketDataType, OnlyReferencePriceKind | None]] = set()
    if policy.valuation_policy is not None:
        for kind in {
            policy.valuation_policy.unrealized_price_kind,
            policy.valuation_policy.margin_price_kind,
        }:
            if kind is not OnlyReferencePriceKind.TRADE:
                requirements.add((OnlyMarketDataType.REFERENCE_PRICE, kind))
    if policy.funding_policy is not None:
        requirements.add((OnlyMarketDataType.FUNDING_RATE, None))
        if policy.funding_policy.valuation_price_kind is not OnlyReferencePriceKind.TRADE:
            requirements.add((OnlyMarketDataType.REFERENCE_PRICE, policy.funding_policy.valuation_price_kind))
    if policy.variation_margin_policy is not None:
        requirements.add((OnlyMarketDataType.SETTLEMENT, OnlyReferencePriceKind.SETTLEMENT))
    return tuple(
        OnlyKernelEconomicInputRequirement(family, kind)
        for family, kind in sorted(
            requirements,
            key=lambda item: (item[0].value, "" if item[1] is None else item[1].value),
        )
    )


def only_historical_market_data_input_plan(
    runtime_id: OnlyRuntimeId,
    graph: OnlyMarketDataConstructionGraph,
    data_range: OnlyHistoricalDataRange,
    data_version: OnlyDataVersion,
    *,
    batch_size: int,
) -> OnlyHistoricalMarketDataInputPlan:
    bar_types = frozenset(item for item in graph.provider_inputs if isinstance(item, OnlyBarType))
    trade_instruments = frozenset(
        item.instrument_id for item in graph.provider_inputs if isinstance(item, OnlyTradeInputType)
    )
    return OnlyHistoricalMarketDataInputPlan(
        (
            OnlyHistoricalBarRequest(
                f"{runtime_id}-historical-bars",
                frozenset(item.instrument_id for item in bar_types),
                bar_types,
                data_range,
                data_version,
                batch_size=batch_size,
            ),
        )
        if bar_types
        else (),
        (
            OnlyHistoricalTradeRequest(
                f"{runtime_id}-historical-trades",
                trade_instruments,
                data_range,
                data_version,
                batch_size=batch_size,
            ),
        )
        if trade_instruments
        else (),
    )


__all__ = [name for name in globals() if name.startswith(("Only", "only_"))]
