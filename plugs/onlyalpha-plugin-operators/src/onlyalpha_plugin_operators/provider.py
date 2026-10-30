"""Operator quantitative asset provider facade."""

from onlyalpha.quant_assets import (
    OnlyDistributionProviderSource,
    OnlyQuantAssetKind,
    OnlyQuantAssetProvider,
    OnlyQuantAssetProviderManifest,
)
from onlyalpha_plugin_operators.metadata import DISTRIBUTION_NAME, DISTRIBUTION_VERSION, PROVIDER_ID, PROVIDER_VERSION
from onlyalpha_plugin_operators.registration import registrations


def quant_asset_provider() -> OnlyQuantAssetProvider:
    return OnlyQuantAssetProvider(
        OnlyQuantAssetProviderManifest(
            provider_id=PROVIDER_ID,
            provider_version=PROVIDER_VERSION,
            kind=OnlyQuantAssetKind.OPERATOR,
            source=OnlyDistributionProviderSource(DISTRIBUTION_NAME, DISTRIBUTION_VERSION),
        ),
        calculation_registrations=registrations(),
    )


__all__ = ["quant_asset_provider"]
