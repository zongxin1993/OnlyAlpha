"""L3 quantitative asset provider facade."""

from onlyalpha.quant_assets import (
    OnlyQuantAssetLayer,
    OnlyQuantAssetProvider,
    OnlyQuantAssetProviderManifest,
)
from onlyalpha_example_alpha.registration import registrations


def quant_asset_provider() -> OnlyQuantAssetProvider:
    return OnlyQuantAssetProvider(
        OnlyQuantAssetProviderManifest(
            provider_id="example.alpha.library",
            provider_version="1",
            layer=OnlyQuantAssetLayer.FACTOR,
            distribution_name="onlyalpha-example-alpha",
            distribution_version="0.9.9",
        ),
        calculation_registrations=registrations(),
    )


__all__ = ["quant_asset_provider"]
