"""Test-only construction of concrete Market Product bindings through public factories."""

from typing import Any, cast

from onlyalpha_plugin_cn_ashare.factory import OnlyCnAshareMarketProductFactory
from onlyalpha_plugin_generic_t0_cash.factory import OnlyGenericT0CashMarketProductFactory

from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.market.product import (
    OnlyCanonicalMarketProductConfig,
    OnlyMarketProductConfig,
    OnlyMarketProductConfigValue,
    OnlyMarketProductId,
    OnlyMarketProductPluginId,
    OnlyMarketProductResolutionContext,
    OnlyMarketProductVersion,
    OnlyResolvedMarketProductBinding,
)


class _NoResources:
    def require_reference_authority(self, resource_id: str) -> Any:
        raise AssertionError(resource_id)

    def require_market_fee_pack(self, pack_id: str, pack_version: str) -> Any:
        raise AssertionError((pack_id, pack_version))


def only_generic_market_product(instrument: OnlyInstrument) -> OnlyResolvedMarketProductBinding:
    config = OnlyMarketProductConfig(
        OnlyMarketProductPluginId("onlyalpha-plugin-generic-t0-cash"),
        OnlyMarketProductId("GENERIC_T0_CASH"),
        OnlyMarketProductVersion("1"),
        OnlyCanonicalMarketProductConfig(),
    )
    return OnlyGenericT0CashMarketProductFactory().resolve(
        config, OnlyMarketProductResolutionContext(_NoResources(), (instrument,))
    )


def only_cn_ashare_market_product(
    instrument: OnlyInstrument,
    *,
    previous_close: str,
    product_version: str = "2025.1",
) -> OnlyResolvedMarketProductBinding:
    venue = str(instrument.instrument_id.venue)
    reference = {
        "instrument_id": str(instrument.instrument_id),
        "exchange": "SSE" if venue == "XSHG" else "SZSE",
        "security_type": "COMMON_STOCK",
        "board": "SSE_MAIN" if venue == "XSHG" else "SZSE_MAIN",
        "lot_size": str(instrument.lot_size.value if instrument.lot_size else 100),
        "price_tick": str(instrument.tick_size.value),
        "st_status": False,
        "suspended": False,
        "previous_close": previous_close,
        "effective_from": "2025-01-01",
        "effective_to": None,
        "source": "SCENARIO",
        "source_version": "integration-v1",
        "data_version": "integration-v1",
    }
    config = OnlyMarketProductConfig(
        OnlyMarketProductPluginId("onlyalpha-plugin-cn-ashare"),
        OnlyMarketProductId("CN_A_SHARE_CASH"),
        OnlyMarketProductVersion(product_version),
        OnlyCanonicalMarketProductConfig(cast(dict[str, OnlyMarketProductConfigValue], {"references": (reference,)})),
    )
    return OnlyCnAshareMarketProductFactory().resolve(config, OnlyMarketProductResolutionContext(_NoResources()))


__all__ = ["only_cn_ashare_market_product", "only_generic_market_product"]
