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
    OnlyArtifactCalculationImplementation,
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
actual_algorithms = "--actual-algorithms" in sys.argv
algorithm_root = root.parent / "algorithms"
algorithm_wheels = root.parent / "wheels"
algorithm_info: dict[str, str] = {}
if actual_algorithms:
    sys.path.insert(0, str(Path(__file__).resolve().parents[5]))
    from scripts.build_algorithm_sdk import install

    algorithm_artifact = install(algorithm_wheels, algorithm_root)
    algorithm_info = {"algorithm_root": str(algorithm_root), "algorithm_artifact": algorithm_artifact}
core_bytes = b"controlled core bytes; this fixture proves storage, not SDK compatibility"
if actual_algorithms:
    core_bytes = next(algorithm_wheels.glob("onlyalpha-*.whl")).read_bytes()
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
if actual_algorithms:
    provider_bytes = next(algorithm_wheels.glob("onlyalpha_plugin_operators-*.whl")).read_bytes()
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
# Actual public Target declarations, with controlled retained bytes. This is a
# CALCULATION artifact, not a Quant Asset Provider or executable certification.
extra_calculations = []
if "--strategy-targets" in sys.argv:
    from onlyalpha_backend_algorithms.targets.registration import registrations as target_registrations

    target_bytes = b"controlled target bytes; no executable certification"
    if actual_algorithms:
        target_bytes = next(algorithm_wheels.glob("onlyalpha_backend_algorithms-*.whl")).read_bytes()
    target_manifest = OnlyDistributionArtifactManifest(
        OnlyDistributionArtifactRole.CALCULATION,
        OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
        "OnlyAlpha",
        "2" * 40,
        "onlyalpha-backend-algorithms",
        "0.11.1",
        "onlyalpha_backend_algorithms-0.11.1-py3-none-any.whl",
        hashlib.sha256(target_bytes).hexdigest(),
        len(target_bytes),
        core.fingerprint,
        implementations=tuple(
            OnlyArtifactCalculationImplementation(
                r.type_definition.kind.value,
                r.type_definition.type_id,
                r.type_definition.semantic_version,
                r.backend.value,
                r.implementation_manifest.implementation_fingerprint,
            )
            for r in target_registrations()
            if r.implementation_manifest is not None
        ),
    )
    artifacts.put_once(target_manifest, target_bytes)
    extra_calculations.append(target_manifest)

catalog_fingerprint = "4" * 64
if "--strategy-targets" in sys.argv:
    from onlyalpha.quant_assets import OnlyQuantAssetCatalogGeneration

    catalog_fingerprint = OnlyQuantAssetCatalogGeneration((provider,)).generation_fingerprint
manifest = OnlyRuntimeGenerationManifest(
    core,
    (
        core_manifest.manifest_fingerprint,
        provider_manifest.manifest_fingerprint,
        native_manifest.manifest_fingerprint,
        *(m.manifest_fingerprint for m in extra_calculations),
    ),
    (
        core_manifest.artifact_sha256,
        provider_manifest.artifact_sha256,
        native_manifest.artifact_sha256,
        *(m.artifact_sha256 for m in extra_calculations),
    ),
    (
        OnlyRuntimeProviderBinding(
            provider.manifest.provider_id,
            provider.manifest.provider_version,
            provider.content_fingerprint,
            provider_manifest.artifact_sha256,
        ),
    ),
    catalog_fingerprint,
    (*provider_manifest.implementations, *(i for m in extra_calculations for i in m.implementations)),
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
        print(json.dumps({"generation": g, "ready": sg, **algorithm_info}))
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
print(json.dumps({"generation": g, **algorithm_info}))
