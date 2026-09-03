"""L4 quantitative asset provider facade."""

import json

from onlyalpha.quant_assets import (
    OnlyQuantAssetLayer,
    OnlyQuantAssetProvider,
    OnlyQuantAssetProviderManifest,
    OnlyStrategyAuthoringAsset,
    OnlyStrategyAuthoringResource,
)
from onlyalpha_example_strategies import read_strategy_definition, strategy_asset_resource


def quant_asset_provider() -> OnlyQuantAssetProvider:
    definition = read_strategy_definition("simple_momentum").encode("utf-8")
    metadata = strategy_asset_resource("simple_momentum", "metadata.json").read_bytes()
    metadata_payload = json.loads(metadata)
    if not isinstance(metadata_payload, dict) or not isinstance(metadata_payload.get("asset_version"), str):
        raise ValueError("Strategy asset metadata requires asset_version")
    asset = OnlyStrategyAuthoringAsset(
        "example.strategy.simple_momentum",
        metadata_payload["asset_version"],
        (
            OnlyStrategyAuthoringResource("metadata.json", metadata),
            OnlyStrategyAuthoringResource("research-definition.json", definition),
        ),
    )
    return OnlyQuantAssetProvider(
        OnlyQuantAssetProviderManifest(
            provider_id="example.strategy.library",
            provider_version="1",
            layer=OnlyQuantAssetLayer.STRATEGY,
            distribution_name="onlyalpha-example-strategies",
            distribution_version="0.9.8",
        ),
        strategy_assets=(asset,),
    )


__all__ = ["quant_asset_provider"]
