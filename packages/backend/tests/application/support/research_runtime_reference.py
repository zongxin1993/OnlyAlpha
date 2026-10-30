"""Existing sole ledger writer, controlled fixture; not executable certification."""

import hashlib
import json
import platform
import struct
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from onlyalpha_gateway_protocol.distribution import (
    OnlyArtifactSourceProvenanceAuthority,
    OnlyDistributionArtifactManifest,
    OnlyDistributionArtifactRole,
)
from onlyalpha_plugin_operators.provider import quant_asset_provider
from onlyalpha_runtime_generation_manager import OnlyLocalImmutableArtifactStore
from onlyalpha_runtime_generation_manager.registry import OnlyRuntimeGenerationRegistry

from onlyalpha.generation_identity import (
    OnlyCoreExecutionIdentity,
    OnlyRuntimeGenerationManifest,
    OnlyRuntimeGenerationValidationEvidence,
    OnlyRuntimeProviderBinding,
)
from onlyalpha.quant_assets import only_quant_asset_distribution_artifact_manifest

root = Path(sys.argv[1])
registry = OnlyRuntimeGenerationRegistry(root)
core_bytes = b"controlled core bytes; this fixture proves storage, not SDK compatibility"
core_manifest = OnlyDistributionArtifactManifest(
    OnlyDistributionArtifactRole.CORE,
    OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
    "OnlyAlpha",
    "1" * 40,
    "onlyalpha",
    "0.11.1",
    "onlyalpha-0.11.1-py3-none-any.whl",
    hashlib.sha256(core_bytes).hexdigest(),
    len(core_bytes),
)
core = OnlyCoreExecutionIdentity("onlyalpha", "0.11.1", core_manifest.artifact_sha256)
provider = quant_asset_provider()
provider_bytes = b"controlled operator bytes; not an installed algorithm"
provider_manifest = only_quant_asset_distribution_artifact_manifest(
    source_repository="OnlyAlpha",
    source_revision="2" * 40,
    artifact_logical_name="onlyalpha_plugin_operators-0.11.1-py3-none-any.whl",
    artifact_bytes=provider_bytes,
    tested_core_execution_fingerprint=core.fingerprint,
    provider=provider,
)
artifacts = OnlyLocalImmutableArtifactStore(root / "artifacts")
artifacts.put_once(core_manifest, core_bytes)
artifacts.put_once(provider_manifest, provider_bytes)
target = {"aarch64": "aarch64-unknown-linux-gnu", "x86_64": "x86_64-unknown-linux-gnu"}[platform.machine()]
# Controlled ELF envelope only; this is not an executable ABI certification.
header = bytearray(64)
header[:7] = b"\x7fELF\x02\x01\x01"
struct.pack_into("<HHI", header, 16, 3, 183 if platform.machine() == "aarch64" else 62, 1)
struct.pack_into("<H", header, 52, 64)
native_bytes = bytes(header)
native_manifest = OnlyDistributionArtifactManifest(
    OnlyDistributionArtifactRole.RESEARCH_RUNTIME,
    OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
    "OnlyAlpha",
    "3" * 40,
    "onlyalpha-backend",
    "0.11.1",
    f"onlyalpha_backend-0.11.1-{target}.elf",
    hashlib.sha256(native_bytes).hexdigest(),
    len(native_bytes),
    core.fingerprint,
)
artifacts.put_once(native_manifest, native_bytes)
manifest = OnlyRuntimeGenerationManifest(
    core,
    (core_manifest.manifest_fingerprint, provider_manifest.manifest_fingerprint, native_manifest.manifest_fingerprint),
    (core_manifest.artifact_sha256, provider_manifest.artifact_sha256, native_manifest.artifact_sha256),
    (
        OnlyRuntimeProviderBinding(
            provider.manifest.provider_id,
            provider.manifest.provider_version,
            provider.content_fingerprint,
            provider_manifest.artifact_sha256,
        ),
    ),
    "4" * 64,
    provider_manifest.implementations,
)
g = manifest.runtime_generation_fingerprint
now = datetime(2026, 10, 29, tzinfo=UTC)
registry.prepare(manifest, actor="fixture", occurred_at=now)
registry.admit_ready(OnlyRuntimeGenerationValidationEvidence.from_manifest(manifest), actor="fixture", occurred_at=now)
registry.activate_for_new_work(target=g, expected_current=None, actor="fixture", occurred_at=now)
registry.bind_new_work_exact("work", g, owner="research", actor="fixture", occurred_at=now)
if len(sys.argv) > 2:
    second = replace(manifest, catalog_generation_fingerprint="5" * 64)
    registry.prepare(second, actor="fixture", occurred_at=now)
    registry.admit_ready(
        OnlyRuntimeGenerationValidationEvidence.from_manifest(second), actor="fixture", occurred_at=now
    )
    sg = second.runtime_generation_fingerprint
    if sys.argv[2] == "ready":
        print(json.dumps({"generation": g, "ready": sg}))
        sys.exit(0)
    registry.activate_for_new_work(target=sg, expected_current=g, actor="fixture", occurred_at=now)
    registry.bind_new_work_exact("other", sg, owner="research", actor="fixture", occurred_at=now)
    registry.release_work("other", actor="fixture", occurred_at=now)
    registry.close_new_work_exact(
        "other", sg, owner="research", closure_reason="fixture", actor="fixture", occurred_at=now
    )
    third = replace(manifest, catalog_generation_fingerprint="6" * 64)
    registry.prepare(third, actor="fixture", occurred_at=now)
    registry.reject(third.runtime_generation_fingerprint, actor="fixture", occurred_at=now, reason="fixture")
    fourth = replace(manifest, catalog_generation_fingerprint="7" * 64)
    registry.prepare(fourth, actor="fixture", occurred_at=now)
    registry.admit_ready(
        OnlyRuntimeGenerationValidationEvidence.from_manifest(fourth), actor="fixture", occurred_at=now
    )
    registry.activate_for_new_work(
        target=fourth.runtime_generation_fingerprint, expected_current=sg, actor="fixture", occurred_at=now
    )
    registry.retire(sg, actor="fixture", occurred_at=now)
print(json.dumps({"generation": g}))
