"""Test-only isolated bootstrap: author exact variant artifacts, never host work."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from onlyalpha_example_alpha.provider import quant_asset_provider as alpha_provider
from onlyalpha_plugin_indicators.provider import quant_asset_provider as indicator_provider
from onlyalpha_plugin_operators.provider import quant_asset_provider as operator_provider
from onlyalpha_runtime_generation_manager import OnlyLocalImmutableArtifactStore, OnlyRuntimeGenerationBuilder

from onlyalpha.quant_assets import OnlyQuantAssetCatalogGeneration, only_quant_asset_distribution_artifact_manifest
from onlyalpha.runtime.generation import OnlyDistributionArtifactManifest


def main() -> None:
    configuration = json.loads(Path(sys.argv[1]).read_text())
    root = Path(configuration["root"])
    artifacts = tuple(OnlyDistributionArtifactManifest.from_dict(item) for item in configuration["artifacts"])
    wheel = Path(configuration["variant_wheel"])
    variant = only_quant_asset_distribution_artifact_manifest(
        source_repository="OnlyAlpha-test-fixture",
        source_revision="b" * 40,
        artifact_logical_name=wheel.name,
        artifact_bytes=wheel.read_bytes(),
        tested_core_execution_fingerprint=configuration["core_identity"],
        provider=alpha_provider(),
    )
    store = OnlyLocalImmutableArtifactStore(root / "artifacts")
    store.put_once(variant, wheel.read_bytes())
    selected = tuple(item for item in artifacts if item.distribution_name != "onlyalpha-example-alpha") + (variant,)
    catalog = OnlyQuantAssetCatalogGeneration((operator_provider(), indicator_provider(), alpha_provider()))
    validated = OnlyRuntimeGenerationBuilder(store, Path(sys.executable)).build_validated(
        artifacts=selected, expected_catalog=catalog, environment_root=root / "variant-built"
    )
    print(json.dumps({"manifest": validated.manifest.to_dict(), "evidence": validated.validation_evidence.to_dict()}))


if __name__ == "__main__":
    main()
