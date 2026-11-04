"""Normal entry-point assembly for Binance USD-M Research/Backtest."""

from dataclasses import dataclass

from onlyalpha.identity import only_identity_fingerprint
from onlyalpha.market.economics import (
    OnlyEffectiveTradingProfile,
    OnlyProviderCapabilityEnvelope,
    OnlyRequestedTradingProfile,
)
from onlyalpha.market.product import (
    OnlyMarketProductConfig,
    OnlyMarketProductId,
    OnlyMarketProductIdentity,
    OnlyMarketProductPluginId,
    OnlyMarketProductResolutionContext,
    OnlyMarketProductVersion,
    OnlyResolvedMarketProductBinding,
    OnlyUnsupportedMarketProductError,
    OnlyUnsupportedMarketProductVersionError,
)

from .compiler import OnlyBinanceUsdmPolicyCompiler
from .config import OnlyBinanceUsdmConfig
from .fee_pack import only_binance_usdm_baseline_fee_pack
from .reference import (
    BINANCE_USDM_CAPABILITY,
    OnlyBinanceUsdmAccountReferenceAuthority,
    OnlyBinanceUsdmPublicReferenceAuthority,
)

PLUGIN_ID = OnlyMarketProductPluginId("onlyalpha-plugin-binance-usdm")
PRODUCT_ID = OnlyMarketProductId("BINANCE_USDM")
PRODUCT_VERSION = OnlyMarketProductVersion("2")


@dataclass(frozen=True, slots=True)
class OnlyBinanceUsdmMarketProductFactory:
    plugin_id: OnlyMarketProductPluginId = PLUGIN_ID

    def resolve(
        self, config: OnlyMarketProductConfig, context: OnlyMarketProductResolutionContext
    ) -> OnlyResolvedMarketProductBinding:
        if config.plugin_id != self.plugin_id:
            raise ValueError("BINANCE_USDM_PLUGIN_IDENTITY_MISMATCH")
        if config.product_id != PRODUCT_ID:
            raise OnlyUnsupportedMarketProductError("UNSUPPORTED_MARKET_PRODUCT", str(config.product_id))
        if config.product_version != PRODUCT_VERSION:
            raise OnlyUnsupportedMarketProductVersionError(
                "UNSUPPORTED_MARKET_PRODUCT_VERSION", str(config.product_version)
            )
        typed = OnlyBinanceUsdmConfig.parse(config.config)
        public = context.resources.require_reference_authority(typed.public_reference_resource_id)
        account = context.resources.require_reference_authority(typed.account_reference_resource_id)
        if not isinstance(public, OnlyBinanceUsdmPublicReferenceAuthority):
            raise TypeError("BINANCE_USDM_PUBLIC_REFERENCE_AUTHORITY_REQUIRED")
        if not isinstance(account, OnlyBinanceUsdmAccountReferenceAuthority):
            raise TypeError("BINANCE_USDM_ACCOUNT_REFERENCE_AUTHORITY_REQUIRED")
        if public.identity.authority_fingerprint != typed.expected_public_reference_fingerprint:
            raise ValueError("BINANCE_USDM_EXPECTED_PUBLIC_REFERENCE_FINGERPRINT_MISMATCH")
        if account.identity.authority_fingerprint != typed.expected_account_reference_fingerprint:
            raise ValueError("BINANCE_USDM_EXPECTED_ACCOUNT_REFERENCE_FINGERPRINT_MISMATCH")
        requested = OnlyRequestedTradingProfile(
            typed.requested_position_mode, typed.requested_margin_mode, typed.requested_leverage
        )
        profile = OnlyEffectiveTradingProfile.resolve(
            OnlyProviderCapabilityEnvelope(*BINANCE_USDM_CAPABILITY),
            requested,
            account.effective_inputs,
        )
        return OnlyResolvedMarketProductBinding.create(
            product_identity=OnlyMarketProductIdentity(PRODUCT_ID, PRODUCT_VERSION),
            provider_plugin_id=self.plugin_id,
            reference_authority=public,
            policy_compiler=OnlyBinanceUsdmPolicyCompiler(account),
            market_fee_pack=only_binance_usdm_baseline_fee_pack(typed.maker_fee_rate, typed.taker_fee_rate),
            effective_config_fingerprint=only_identity_fingerprint(
                (
                    public.identity,
                    account.identity,
                    requested,
                    typed.maker_fee_rate,
                    typed.taker_fee_rate,
                )
            ),
            effective_trading_profile=profile,
        )


__all__ = ["OnlyBinanceUsdmMarketProductFactory"]
