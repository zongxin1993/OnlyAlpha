"""Thin Core ports implemented by concrete Trading Market Product plugins."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from onlyalpha.fee.market_pack import OnlyMarketFeePack
from onlyalpha.market.product.config import OnlyMarketProductConfig
from onlyalpha.market.product.identity import OnlyMarketProductPluginId
from onlyalpha.market.product.ports import OnlyMarketReferenceAuthority

if TYPE_CHECKING:
    from onlyalpha.market.product.binding import OnlyResolvedMarketProductBinding


class OnlyMarketProductResourceResolver(Protocol):
    """Composition-time resources only; Runtime mutable authorities are intentionally absent."""

    def require_reference_authority(self, resource_id: str) -> OnlyMarketReferenceAuthority: ...

    def require_market_fee_pack(self, pack_id: str, pack_version: str) -> OnlyMarketFeePack: ...


@dataclass(frozen=True, slots=True)
class OnlyMarketProductResolutionContext:
    resources: OnlyMarketProductResourceResolver


class OnlyMarketProductFactory(Protocol):
    @property
    def plugin_id(self) -> OnlyMarketProductPluginId: ...

    def resolve(
        self,
        config: OnlyMarketProductConfig,
        context: OnlyMarketProductResolutionContext,
    ) -> OnlyResolvedMarketProductBinding: ...


__all__ = [name for name in globals() if name.startswith("Only")]
