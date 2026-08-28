"""Offline exact-resource Binance Spot Market Product factory."""

from dataclasses import dataclass

from onlyalpha.plugin.api import (
    OnlyMarketProductConfig,
    OnlyMarketProductId,
    OnlyMarketProductIdentity,
    OnlyMarketProductPluginId,
    OnlyMarketProductResolutionContext,
    OnlyMarketProductVersion,
    OnlyResolvedMarketProductBinding,
    OnlyUnsupportedMarketProductError,
    OnlyUnsupportedMarketProductVersionError,
    only_identity_fingerprint,
)
from onlyalpha_market_binance_spot.compiler import OnlyBinanceSpotPolicyCompiler
from onlyalpha_market_binance_spot.config import OnlyBinanceSpotConfig
from onlyalpha_market_binance_spot.fee_pack import only_binance_spot_baseline_fee_pack
from onlyalpha_market_binance_spot.reference import OnlyBinanceSpotReferenceAuthority

PLUGIN_ID = OnlyMarketProductPluginId("onlyalpha-market-binance-spot")
PRODUCT_ID = OnlyMarketProductId("BINANCE_SPOT")
PRODUCT_VERSION = OnlyMarketProductVersion("1")


@dataclass(frozen=True, slots=True)
class OnlyBinanceSpotMarketProductFactory:
    plugin_id: OnlyMarketProductPluginId = PLUGIN_ID

    def resolve(
        self, config: OnlyMarketProductConfig, context: OnlyMarketProductResolutionContext
    ) -> OnlyResolvedMarketProductBinding:
        if config.plugin_id != self.plugin_id:
            raise ValueError("BINANCE_SPOT_PLUGIN_IDENTITY_MISMATCH")
        if config.product_id != PRODUCT_ID:
            raise OnlyUnsupportedMarketProductError("UNSUPPORTED_MARKET_PRODUCT", str(config.product_id))
        if config.product_version != PRODUCT_VERSION:
            raise OnlyUnsupportedMarketProductVersionError(
                "UNSUPPORTED_MARKET_PRODUCT_VERSION", str(config.product_version)
            )
        typed = OnlyBinanceSpotConfig.parse(config.config)
        authority = context.resources.require_reference_authority(typed.reference_resource_id)
        if not isinstance(authority, OnlyBinanceSpotReferenceAuthority):
            raise TypeError("BINANCE_SPOT_REFERENCE_AUTHORITY_REQUIRED")
        if authority.identity.authority_fingerprint != typed.expected_reference_fingerprint:
            raise ValueError("BINANCE_SPOT_EXPECTED_REFERENCE_FINGERPRINT_MISMATCH")
        return OnlyResolvedMarketProductBinding.create(
            product_identity=OnlyMarketProductIdentity(PRODUCT_ID, PRODUCT_VERSION),
            provider_plugin_id=self.plugin_id,
            reference_authority=authority,
            policy_compiler=OnlyBinanceSpotPolicyCompiler(),
            market_fee_pack=only_binance_spot_baseline_fee_pack(typed.maker_fee_rate, typed.taker_fee_rate),
            effective_config_fingerprint=only_identity_fingerprint((typed.maker_fee_rate, typed.taker_fee_rate)),
        )


__all__ = ["OnlyBinanceSpotMarketProductFactory"]
