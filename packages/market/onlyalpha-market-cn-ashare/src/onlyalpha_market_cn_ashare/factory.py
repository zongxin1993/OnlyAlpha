"""CN A-share concrete Market Product factory."""

from __future__ import annotations

from dataclasses import dataclass

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
from onlyalpha_market_cn_ashare.compiler import OnlyCnAsharePolicyCompiler
from onlyalpha_market_cn_ashare.config import OnlyCnAshareConfig
from onlyalpha_market_cn_ashare.fee_pack import only_cn_a_share_market_fee_pack
from onlyalpha_market_cn_ashare.reference import OnlyCnAshareReferenceAuthority

PLUGIN_ID = OnlyMarketProductPluginId("onlyalpha-market-cn-ashare")
PRODUCT_ID = OnlyMarketProductId("CN_A_SHARE_CASH")
SUPPORTED_VERSIONS = frozenset({"2025.1", "2026.07"})


@dataclass(frozen=True, slots=True)
class OnlyCnAshareMarketProductFactory:
    plugin_id: OnlyMarketProductPluginId = PLUGIN_ID

    def resolve(
        self, config: OnlyMarketProductConfig, context: OnlyMarketProductResolutionContext
    ) -> OnlyResolvedMarketProductBinding:
        del context
        if config.plugin_id != self.plugin_id:
            raise ValueError("CN_A_SHARE_PROVIDER_IDENTITY_MISMATCH")
        if config.product_id != PRODUCT_ID:
            raise OnlyUnsupportedMarketProductError("UNSUPPORTED_MARKET_PRODUCT", str(config.product_id))
        if config.product_version.value not in SUPPORTED_VERSIONS:
            raise OnlyUnsupportedMarketProductVersionError(
                "UNSUPPORTED_MARKET_PRODUCT_VERSION", str(config.product_version)
            )
        typed = OnlyCnAshareConfig.parse(config.config)
        reference = OnlyCnAshareReferenceAuthority.create(typed.references)
        compiler = OnlyCnAsharePolicyCompiler.create(config.product_version.value)
        fee_pack = only_cn_a_share_market_fee_pack()
        identity = OnlyMarketProductIdentity(PRODUCT_ID, OnlyMarketProductVersion(config.product_version.value))
        composition = OnlyMarketProductCompositionIdentity.create(
            product_identity=identity,
            reference_authority=reference.identity,
            policy_compiler=compiler.identity,
            market_fee_pack=fee_pack.identity,
            effective_config_fingerprint=only_canonical_fingerprint(()),
        )
        return OnlyResolvedMarketProductBinding(identity, self.plugin_id, reference, compiler, fee_pack, composition)


__all__ = ["OnlyCnAshareMarketProductFactory"]
