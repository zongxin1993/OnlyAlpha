"""L1 quantitative asset provider facade."""

from onlyalpha.quant_assets import (
    OnlyQuantAssetLayer,
    OnlyQuantAssetProvider,
    OnlyQuantAssetProviderManifest,
)
from onlyalpha_plugin_operators.registration import registrations


def quant_asset_provider() -> OnlyQuantAssetProvider:
    return OnlyQuantAssetProvider(
        OnlyQuantAssetProviderManifest(
            provider_id="onlyalpha.operator.library",
            provider_version="4",
            layer=OnlyQuantAssetLayer.OPERATOR,
            distribution_name="onlyalpha-plugin-operators",
            distribution_version="0.9.9",
        ),
        calculation_registrations=registrations(),
    )


__all__ = ["quant_asset_provider"]
