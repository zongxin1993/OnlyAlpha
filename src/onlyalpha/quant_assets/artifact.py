"""Derive the public immutable artifact contract from one exact provider and byte payload."""

from __future__ import annotations

import hashlib

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.distribution import (
    OnlyArtifactAssetIdentity,
    OnlyArtifactCalculationImplementation,
    OnlyDistributionArtifactManifest,
    OnlyDistributionArtifactRole,
)

from .catalog import OnlyQuantAssetProvider


def only_quant_asset_distribution_artifact_manifest(
    *,
    source_repository: str,
    source_revision: str,
    artifact_logical_name: str,
    artifact_bytes: bytes,
    tested_core_execution_fingerprint: str,
    provider: OnlyQuantAssetProvider,
) -> OnlyDistributionArtifactManifest:
    """Bind release bytes to the exact public Provider content they must supply when installed."""

    if not artifact_bytes:
        raise ValueError("RUNTIME_GENERATION_ARTIFACT_MANIFEST_INVALID")
    implementations: list[OnlyArtifactCalculationImplementation] = []
    semantic_assets: dict[tuple[str, str, str], OnlyArtifactAssetIdentity] = {}
    for registration in provider.calculation_registrations:
        implementation = registration.implementation_manifest
        if implementation is None:
            raise ValueError("RUNTIME_GENERATION_IMPLEMENTATION_MISMATCH")
        definition = registration.type_definition
        semantic_key = (definition.kind.value, definition.type_id, definition.semantic_version)
        semantic_assets.setdefault(
            semantic_key,
            OnlyArtifactAssetIdentity(
                definition.kind.value,
                definition.type_id,
                definition.semantic_version,
                only_canonical_fingerprint(definition.descriptor()),
            ),
        )
        implementations.append(
            OnlyArtifactCalculationImplementation(
                kind=definition.kind.value,
                type_id=definition.type_id,
                semantic_version=definition.semantic_version,
                backend=registration.backend.value,
                implementation_fingerprint=implementation.implementation_fingerprint,
            )
        )
    for asset in provider.strategy_assets:
        semantic_assets[("STRATEGY", asset.asset_id, asset.semantic_version)] = OnlyArtifactAssetIdentity(
            "STRATEGY",
            asset.asset_id,
            asset.semantic_version,
            asset.content_fingerprint,
        )
    return OnlyDistributionArtifactManifest(
        role=OnlyDistributionArtifactRole.QUANT_ASSET,
        source_repository=source_repository,
        source_revision=source_revision,
        distribution_name=provider.manifest.distribution_name,
        distribution_version=provider.manifest.distribution_version,
        artifact_logical_name=artifact_logical_name,
        artifact_sha256=hashlib.sha256(artifact_bytes).hexdigest(),
        artifact_size=len(artifact_bytes),
        tested_core_execution_fingerprint=tested_core_execution_fingerprint,
        provider_id=provider.manifest.provider_id,
        provider_version=provider.manifest.provider_version,
        provider_content_fingerprint=provider.content_fingerprint,
        assets=tuple(semantic_assets.values()),
        implementations=tuple(implementations),
    )


__all__ = ["only_quant_asset_distribution_artifact_manifest"]
