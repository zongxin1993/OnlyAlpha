"""Binance USD-M provider-boundary adapters."""

from .data_source import (
    OnlyBinanceUsdmDataSource,
    OnlyBinanceUsdmDataSourceConfig,
    OnlyBinanceUsdmDataSourceFactory,
    OnlyBinanceUsdmHistoricalClient,
    only_normalize_binance_usdm_kline,
)
from .historical import OnlyBinanceUsdmHistoricalNormalizer
from .market_product import (
    OnlyBinanceUsdmPolicyCompiler,
    OnlyBinanceUsdmReference,
    OnlyBinanceUsdmReferenceAuthority,
)
from .reference import OnlyBinanceUsdmReferenceCapture, OnlyBinanceUsdmReferenceClient

__all__ = [
    "OnlyBinanceUsdmHistoricalNormalizer",
    "OnlyBinanceUsdmHistoricalClient",
    "OnlyBinanceUsdmDataSource",
    "OnlyBinanceUsdmDataSourceConfig",
    "OnlyBinanceUsdmDataSourceFactory",
    "OnlyBinanceUsdmPolicyCompiler",
    "OnlyBinanceUsdmReference",
    "OnlyBinanceUsdmReferenceAuthority",
    "OnlyBinanceUsdmReferenceCapture",
    "OnlyBinanceUsdmReferenceClient",
    "only_normalize_binance_usdm_kline",
]
