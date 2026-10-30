"""Native Research input runtime shares the existing distribution Authority."""

from dataclasses import replace

import pytest
from onlyalpha_gateway_protocol.distribution import (
    OnlyArtifactSourceProvenanceAuthority,
    OnlyDistributionArtifactManifest,
    OnlyDistributionArtifactRole,
)
from onlyalpha_runtime_generation_manager.builder import OnlyRuntimeGenerationBuilder

from onlyalpha.generation_identity import OnlyCoreExecutionIdentity


def test_research_executor_artifact_requires_exact_core_and_declared_native_shape():
    core = OnlyDistributionArtifactManifest(
        OnlyDistributionArtifactRole.CORE,
        OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
        "OnlyAlpha",
        "a" * 40,
        "onlyalpha",
        "0.11.1",
        "onlyalpha-0.11.1-py3-none-any.whl",
        "1" * 64,
        10,
    )
    identity = OnlyCoreExecutionIdentity("onlyalpha", "0.11.1", core.artifact_sha256)
    executor = OnlyDistributionArtifactManifest(
        OnlyDistributionArtifactRole("RESEARCH_RUNTIME"),
        OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
        "OnlyAlpha",
        "b" * 40,
        "onlyalpha-backend",
        "0.11.1",
        "onlyalpha_backend-0.11.1-aarch64-unknown-linux-gnu.elf",
        "2" * 64,
        10,
        identity.fingerprint,
    )
    assert OnlyDistributionArtifactManifest.from_dict(executor.to_dict()) == executor
    assert OnlyRuntimeGenerationBuilder._core_identity((core, executor)) == identity
    with pytest.raises(ValueError):
        replace(executor, tested_core_execution_fingerprint=None)
    with pytest.raises(ValueError):
        replace(executor, distribution_name="other")
    with pytest.raises(ValueError):
        OnlyRuntimeGenerationBuilder._core_identity((core, executor, executor))
