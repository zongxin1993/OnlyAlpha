"""Test-only Alpha quantitative asset provider facade."""

from onlyalpha.quant_assets import (
    OnlyDistributionProviderSource,
    OnlyQuantAssetKind,
    OnlyQuantAssetProvider,
    OnlyQuantAssetProviderManifest,
)
from onlyalpha_test_alpha_provider.registration import registrations


def quant_asset_provider() -> OnlyQuantAssetProvider:
    return OnlyQuantAssetProvider(
        OnlyQuantAssetProviderManifest(
            provider_id="example.alpha.library",
            provider_version="1",
            kind=OnlyQuantAssetKind.ALPHA,
            source=OnlyDistributionProviderSource("onlyalpha-test-alpha-provider", "0.9.9"),
        ),
        calculation_registrations=registrations(),
    )


__all__ = ["quant_asset_provider"]
