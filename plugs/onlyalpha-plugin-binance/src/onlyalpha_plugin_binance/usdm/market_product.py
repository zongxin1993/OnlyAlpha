"""Compatibility imports; USD-M Market Product authority lives in its market package."""

from onlyalpha_plugin_binance_usdm import (
    OnlyBinanceUsdmPolicyCompiler,
    OnlyBinanceUsdmPublicMarketReference,
    OnlyBinanceUsdmPublicReferenceAuthority,
)

OnlyBinanceUsdmReference = OnlyBinanceUsdmPublicMarketReference
OnlyBinanceUsdmReferenceAuthority = OnlyBinanceUsdmPublicReferenceAuthority

__all__ = [
    "OnlyBinanceUsdmPolicyCompiler",
    "OnlyBinanceUsdmReference",
    "OnlyBinanceUsdmReferenceAuthority",
]
