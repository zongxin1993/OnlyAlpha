"""Versioned four-layer quantitative asset provider and catalog contracts."""

from .catalog import ONLYALPHA_QUANT_ASSET_ENTRY_POINT as ONLYALPHA_QUANT_ASSET_ENTRY_POINT
from .catalog import OnlyQuantAssetCatalogGeneration as OnlyQuantAssetCatalogGeneration
from .catalog import OnlyQuantAssetCatalogManager as OnlyQuantAssetCatalogManager
from .catalog import OnlyQuantAssetLayer as OnlyQuantAssetLayer
from .catalog import OnlyQuantAssetProvider as OnlyQuantAssetProvider
from .catalog import OnlyQuantAssetProviderManifest as OnlyQuantAssetProviderManifest
from .catalog import OnlyStrategyAuthoringAsset as OnlyStrategyAuthoringAsset
from .catalog import OnlyStrategyAuthoringResource as OnlyStrategyAuthoringResource
from .catalog import only_discover_quant_asset_providers as only_discover_quant_asset_providers

__all__ = [name for name in globals() if name.startswith(("Only", "only_", "ONLYALPHA_"))]
