"""Immutable distribution manifest derivation for non-Quant-Asset Calculation providers."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from onlyalpha.distribution import (
    OnlyArtifactCalculationImplementation,
    OnlyDistributionArtifactManifest,
    OnlyDistributionArtifactRole,
)

from .registry import OnlyCalculationBackendRegistration


def only_calculation_distribution_artifact_manifest(
    *,
    source_repository: str,
    source_revision: str,
    distribution_name: str,
    distribution_version: str,
    artifact_logical_name: str,
    artifact_bytes: bytes,
    tested_core_execution_fingerprint: str,
    registrations: Iterable[OnlyCalculationBackendRegistration],
) -> OnlyDistributionArtifactManifest:
    implementations = []
    for registration in registrations:
        manifest = registration.implementation_manifest
        if manifest is None:
            raise ValueError("RUNTIME_GENERATION_IMPLEMENTATION_MISMATCH")
        definition = registration.type_definition
        implementations.append(
            OnlyArtifactCalculationImplementation(
                definition.kind.value,
                definition.type_id,
                definition.semantic_version,
                registration.backend.value,
                manifest.implementation_fingerprint,
            )
        )
    if not artifact_bytes or not implementations:
        raise ValueError("RUNTIME_GENERATION_ARTIFACT_MANIFEST_INVALID")
    return OnlyDistributionArtifactManifest(
        role=OnlyDistributionArtifactRole.CALCULATION,
        source_repository=source_repository,
        source_revision=source_revision,
        distribution_name=distribution_name,
        distribution_version=distribution_version,
        artifact_logical_name=artifact_logical_name,
        artifact_sha256=hashlib.sha256(artifact_bytes).hexdigest(),
        artifact_size=len(artifact_bytes),
        tested_core_execution_fingerprint=tested_core_execution_fingerprint,
        implementations=tuple(implementations),
    )


__all__ = ["only_calculation_distribution_artifact_manifest"]
