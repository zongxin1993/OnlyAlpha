from dataclasses import replace

import pytest
from onlyalpha_example_alpha.provider import quant_asset_provider
from onlyalpha_plugin_targets.registration import registrations as target_registrations

from onlyalpha.calculation import only_calculation_distribution_artifact_manifest
from onlyalpha.quant_assets import only_quant_asset_distribution_artifact_manifest
from onlyalpha.runtime.generation import (
    OnlyArtifactSourceProvenanceAuthority,
    OnlyCoreExecutionIdentity,
    OnlyDistributionArtifactManifest,
    OnlyDistributionArtifactRole,
    OnlyRuntimeGenerationManifest,
    OnlyRuntimeProviderBinding,
)


def test_artifact_identity_is_exact_bytes_and_locator_independent() -> None:
    core = OnlyCoreExecutionIdentity("onlyalpha", "0.9.9", "a" * 64)
    provider = quant_asset_provider()
    first = only_quant_asset_distribution_artifact_manifest(
        source_repository="OnlyAlpha-example-alpha",
        source_revision="1" * 40,
        artifact_logical_name="onlyalpha_example_alpha-0.9.9-py3-none-any.whl",
        artifact_bytes=b"exact wheel bytes",
        tested_core_execution_fingerprint=core.fingerprint,
        provider=provider,
    )
    relocated = replace(first)
    assert first.artifact_identity == relocated.artifact_identity
    assert first.artifact_size == len(b"exact wheel bytes")
    assert {item.kind for item in first.assets} == {"FACTOR"}
    assert {item.backend for item in first.implementations} == {"RESEARCH", "TRADING"}
    assert OnlyDistributionArtifactManifest.from_dict(first.to_dict()) == first


def test_runtime_generation_identity_excludes_operational_process_details() -> None:
    core = OnlyCoreExecutionIdentity("onlyalpha", "0.9.9", "a" * 64)
    provider = quant_asset_provider()
    artifact = only_quant_asset_distribution_artifact_manifest(
        source_repository="OnlyAlpha-example-alpha",
        source_revision="1" * 40,
        artifact_logical_name="onlyalpha_example_alpha-0.9.9-py3-none-any.whl",
        artifact_bytes=b"exact wheel bytes",
        tested_core_execution_fingerprint=core.fingerprint,
        provider=provider,
    )
    manifest = OnlyRuntimeGenerationManifest(
        core_execution=core,
        artifact_manifest_fingerprints=("c" * 64, artifact.manifest_fingerprint),
        artifact_sha256s=(core.artifact_sha256, artifact.artifact_sha256),
        providers=(
            OnlyRuntimeProviderBinding(
                provider.manifest.provider_id,
                provider.manifest.provider_version,
                provider.content_fingerprint,
                artifact.artifact_sha256,
            ),
        ),
        catalog_generation_fingerprint="b" * 64,
        implementations=artifact.implementations,
    )
    payload = manifest.to_dict()
    assert not {"pid", "hostname", "path", "url", "started_at"} & set(payload)
    assert OnlyRuntimeGenerationManifest.from_dict(payload) == manifest
    assert replace(manifest).runtime_generation_fingerprint == manifest.runtime_generation_fingerprint


def test_non_quant_artifact_cannot_claim_provider_identity() -> None:
    with pytest.raises(ValueError, match="RUNTIME_GENERATION_ARTIFACT_MANIFEST_INVALID"):
        OnlyDistributionArtifactManifest(
            role=OnlyDistributionArtifactRole.CORE,
            source_provenance_authority=OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
            source_repository="OnlyAlpha",
            source_revision="1" * 40,
            distribution_name="onlyalpha",
            distribution_version="0.9.9",
            artifact_logical_name="onlyalpha-0.9.9-py3-none-any.whl",
            artifact_sha256="a" * 64,
            artifact_size=1,
            provider_id="parallel.authority",
        )


def test_onlyalpha_git_provenance_rejects_mutable_source_revision() -> None:
    with pytest.raises(ValueError, match="RUNTIME_GENERATION_SOURCE_PROVENANCE_INVALID"):
        OnlyDistributionArtifactManifest(
            role=OnlyDistributionArtifactRole.CORE,
            source_provenance_authority=OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
            source_repository="OnlyAlpha",
            source_revision="master",
            distribution_name="onlyalpha",
            distribution_version="0.9.9",
            artifact_logical_name="onlyalpha-0.9.9-py3-none-any.whl",
            artifact_sha256="a" * 64,
            artifact_size=1,
        )


def test_non_asset_calculation_distribution_binds_exact_entrypoint_implementations() -> None:
    core = OnlyCoreExecutionIdentity("onlyalpha", "0.9.9", "a" * 64)
    artifact = only_calculation_distribution_artifact_manifest(
        source_repository="OnlyAlpha",
        source_revision="b" * 40,
        distribution_name="onlyalpha-plugin-targets",
        distribution_version="0.9.9",
        artifact_logical_name="onlyalpha_plugin_targets-0.9.9-py3-none-any.whl",
        artifact_bytes=b"target wheel",
        tested_core_execution_fingerprint=core.fingerprint,
        registrations=target_registrations(),
    )
    assert artifact.role is OnlyDistributionArtifactRole.CALCULATION
    assert {item.type_id for item in artifact.implementations} == {"onlyalpha.target.forward_return"}
