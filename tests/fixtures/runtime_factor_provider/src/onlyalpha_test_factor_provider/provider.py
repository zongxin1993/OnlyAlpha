"""Test-only Factor quantitative asset provider facade."""

from onlyalpha.quant_assets import (
    OnlyDistributionProviderSource,
    OnlyQuantAssetKind,
    OnlyQuantAssetProvider,
    OnlyQuantAssetProviderManifest,
)
from onlyalpha_test_factor_provider.registration import registrations


def quant_asset_provider() -> OnlyQuantAssetProvider:
    return OnlyQuantAssetProvider(
        OnlyQuantAssetProviderManifest(
            provider_id="example.factor.library",
            provider_version="1",
            kind=OnlyQuantAssetKind.FACTOR,
            source=OnlyDistributionProviderSource("onlyalpha-test-factor-provider", "0.9.9"),
        ),
        calculation_registrations=registrations(),
    )


__all__ = ["quant_asset_provider"]
