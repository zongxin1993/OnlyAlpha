"""Concrete Market Product factory and immutable binding composition."""

from __future__ import annotations

from dataclasses import dataclass, field

from onlyalpha.plugin.api import (
    OnlyMarketProductCompositionIdentity,
    OnlyMarketProductConfig,
    OnlyMarketProductId,
    OnlyMarketProductIdentity,
    OnlyMarketProductPluginId,
    OnlyMarketProductResolutionContext,
    OnlyMarketProductVersion,
    OnlyResolvedMarketProductBinding,
    OnlyUnsupportedMarketProductError,
    OnlyUnsupportedMarketProductVersionError,
    only_canonical_fingerprint,
)
from onlyalpha_market_generic_t0_cash.compiler import OnlyGenericT0CashPolicyCompiler
from onlyalpha_market_generic_t0_cash.config import OnlyGenericT0CashConfig
from onlyalpha_market_generic_t0_cash.fee_pack import only_generic_t0_cash_market_fee_pack

PLUGIN_ID = OnlyMarketProductPluginId("onlyalpha-market-generic-t0-cash")
PRODUCT_ID = OnlyMarketProductId("GENERIC_T0_CASH")
PRODUCT_VERSION = OnlyMarketProductVersion("1")


@dataclass(frozen=True, slots=True)
class OnlyGenericT0CashMarketProductFactory:
    plugin_id: OnlyMarketProductPluginId = PLUGIN_ID
    _compiler: OnlyGenericT0CashPolicyCompiler = field(default_factory=OnlyGenericT0CashPolicyCompiler)

    def resolve(
        self,
        config: OnlyMarketProductConfig,
        context: OnlyMarketProductResolutionContext,
    ) -> OnlyResolvedMarketProductBinding:
        if config.plugin_id != self.plugin_id:
            raise ValueError("GENERIC_T0_CASH_PROVIDER_IDENTITY_MISMATCH")
        if config.product_id != PRODUCT_ID:
            raise OnlyUnsupportedMarketProductError(
                "UNSUPPORTED_MARKET_PRODUCT",
                str(config.product_id),
            )
        if config.product_version != PRODUCT_VERSION:
            raise OnlyUnsupportedMarketProductVersionError(
                "UNSUPPORTED_MARKET_PRODUCT_VERSION",
                str(config.product_version),
            )
        typed = OnlyGenericT0CashConfig.parse(config.config)
        reference_authority = context.resources.require_reference_authority(typed.reference_resource_id)
        fee_pack = only_generic_t0_cash_market_fee_pack()
        identity = OnlyMarketProductIdentity(PRODUCT_ID, PRODUCT_VERSION)
        composition = OnlyMarketProductCompositionIdentity.create(
            product_identity=identity,
            reference_authority=reference_authority.identity,
            policy_compiler=self._compiler.identity,
            market_fee_pack=fee_pack.identity,
            effective_config_fingerprint=only_canonical_fingerprint(()),
        )
        return OnlyResolvedMarketProductBinding(
            identity,
            self.plugin_id,
            reference_authority,
            self._compiler,
            fee_pack,
            composition,
        )


__all__ = ["OnlyGenericT0CashMarketProductFactory"]
