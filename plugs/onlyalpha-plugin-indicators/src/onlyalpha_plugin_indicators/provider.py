"""L2 quantitative asset provider facade."""

from onlyalpha.quant_assets import (
    OnlyQuantAssetLayer,
    OnlyQuantAssetProvider,
    OnlyQuantAssetProviderManifest,
)
from onlyalpha_plugin_indicators.registration import registrations


def quant_asset_provider() -> OnlyQuantAssetProvider:
    return OnlyQuantAssetProvider(
        OnlyQuantAssetProviderManifest(
            provider_id="onlyalpha.indicator.library",
            provider_version="4",
            layer=OnlyQuantAssetLayer.INDICATOR,
            distribution_name="onlyalpha-plugin-indicators",
            distribution_version="0.9.9",
        ),
        calculation_registrations=registrations(),
    )


__all__ = ["quant_asset_provider"]
