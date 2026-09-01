"""Separation of Strategy inputs from Trading Kernel economic inputs."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.domain.trading import OnlyReferencePriceKind
from onlyalpha.market.product import OnlyCompiledMarketPolicy


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


__all__ = ["OnlyKernelEconomicInputRequirement", "only_kernel_economic_input_requirements"]
