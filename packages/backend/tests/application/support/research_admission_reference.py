"""Controlled input-eligibility fixture, never native Core or Research certification."""

import hashlib
import platform
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from onlyalpha_backend_algorithms.sdk.private_factor_execution import (
    OnlyPrivateFactorExecutableClosureV1,
    OnlyPrivateFactorIsolatedProgramHost,
)
from onlyalpha_gateway_protocol.distribution import (
    OnlyArtifactSourceProvenanceAuthority,
    OnlyDistributionArtifactManifest,
    OnlyDistributionArtifactRole,
)
from onlyalpha_plugin_operators.provider import quant_asset_provider
from onlyalpha_runtime_generation_manager import OnlyLocalImmutableArtifactStore, OnlyRuntimeGenerationBuilder
from onlyalpha_runtime_generation_manager.registry import OnlyRuntimeGenerationRegistry

from onlyalpha.algorithm.private_factor import ONLY_PRIVATE_FACTOR_API_V1
from onlyalpha.generation_identity import (
    OnlyCoreExecutionIdentity,
    OnlyRuntimeGenerationManifest,
    OnlyRuntimeGenerationValidationEvidence,
    OnlyRuntimeProviderBinding,
)
from onlyalpha.quant_assets import (
    OnlyPrivateFactorDraft,
    OnlyPrivateFactorRevision,
    OnlyPrivateFactorSnapshotProviderSource,
    OnlyQuantAssetCatalogGeneration,
    OnlyQuantAssetKind,
    OnlyQuantAssetProvider,
    OnlyQuantAssetProviderManifest,
    only_quant_asset_distribution_artifact_manifest,
)
from scripts.build_algorithm_sdk import install


def build(
    root: Path,
    native_executable: Path,
    *,
    work_id: str = "research-input-fixture",
    candidate_record: dict[str, Any] | None = None,
    draft_record: dict[str, Any] | None = None,
    algorithm_bundle: tuple[Path, Path, str] | None = None,
) -> dict[str, Any]:
    root.mkdir()
    candidate = {"name": "收盘价观察", "purpose": "准入测试", "hypothesis": "fixture", "expression": {"input": "close"}}
    draft = OnlyPrivateFactorDraft(
        factor_id="private.factor.admission",
        semantic_version="1",
        source_text="def calculate(api, inputs, parameters):\n    return {'value': inputs['close']}\n",
        factor_api_version=1,
        factor_api_contract_fingerprint=ONLY_PRIVATE_FACTOR_API_V1.api_contract_fingerprint,
        input_contract={"close": {"type": "DECIMAL", "missing": True}},
        parameter_contract={},
        output_contract={"value": {"type": "DECIMAL", "missing": True}},
        description="fixture",
        economic_rationale="fixture",
        category="chat",
    )
    if candidate_record is not None:
        candidate = candidate_record
    if draft_record is not None:
        draft = OnlyPrivateFactorDraft.from_dict(draft_record)
    revision = OnlyPrivateFactorRevision.from_draft(draft)
    closure = OnlyPrivateFactorExecutableClosureV1.create(
        revision,
        tuple({k: Decimal(i) for k in draft.input_contract} for i in ("2", "3")),
        {},
        host=OnlyPrivateFactorIsolatedProgramHost(3),
    )
    private = OnlyQuantAssetProvider(
        OnlyQuantAssetProviderManifest(
            "private.admission",
            revision.revision_fingerprint,
            OnlyQuantAssetKind.FACTOR,
            OnlyPrivateFactorSnapshotProviderSource(closure.provider_snapshot.snapshot_fingerprint),
        ),
        calculation_registrations=closure.registrations,
        private_factor_snapshot=closure.provider_snapshot,
    )
    base = quant_asset_provider()
    if algorithm_bundle is None:
        wheels = root / "wheels"
        installation = root / "algorithms"
        artifact = install(wheels, installation)
    else:
        wheels, installation, artifact = algorithm_bundle
    core_bytes = next(wheels.glob("onlyalpha-*.whl")).read_bytes()
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
    provider_bytes = b"controlled-provider-artifact"
    distribution_name = base.manifest.distribution_name.replace("-", "_")
    provider_manifest = only_quant_asset_distribution_artifact_manifest(
        source_repository="OnlyAlpha",
        source_revision="2" * 40,
        artifact_logical_name=f"{distribution_name}-{base.manifest.distribution_version}-py3-none-any.whl",
        artifact_bytes=provider_bytes,
        tested_core_execution_fingerprint=core.fingerprint,
        provider=base,
    )
    store = OnlyLocalImmutableArtifactStore(root / "artifacts")
    store.put_once(core_manifest, core_bytes)
    store.put_once(provider_manifest, provider_bytes)
    native = root / "native-executor"
    shutil.copyfile(native_executable, native)
    subprocess.run(["strip", "--strip-debug", str(native)], check=True)
    native.chmod(0o500)
    native_bytes = native.read_bytes()
    target = {"aarch64": "aarch64-unknown-linux-gnu", "x86_64": "x86_64-unknown-linux-gnu"}[platform.machine()]
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
    OnlyRuntimeGenerationBuilder._verify_native_runtime(native, native_manifest)
    store.put_once(native_manifest, native_bytes)
    base_manifest = OnlyRuntimeGenerationManifest(
        core,
        (
            core_manifest.manifest_fingerprint,
            provider_manifest.manifest_fingerprint,
            native_manifest.manifest_fingerprint,
        ),
        (core_manifest.artifact_sha256, provider_manifest.artifact_sha256, native_manifest.artifact_sha256),
        (
            OnlyRuntimeProviderBinding(
                base.manifest.provider_id,
                base.manifest.provider_version,
                base.content_fingerprint,
                provider_manifest.artifact_sha256,
            ),
        ),
        OnlyQuantAssetCatalogGeneration((base,)).generation_fingerprint,
        provider_manifest.implementations,
    )
    manifest = OnlyRuntimeGenerationBuilder(store, Path(sys.executable)).bind_private_factor_closure(
        base_manifest=base_manifest, expected_catalog=OnlyQuantAssetCatalogGeneration((base, private)), closure=closure
    )
    registry = OnlyRuntimeGenerationRegistry(root)
    at = datetime(2026, 10, 29, tzinfo=UTC)
    registry.prepare(manifest, actor="fixture", occurred_at=at)
    registry.admit_ready(
        OnlyRuntimeGenerationValidationEvidence.from_manifest(manifest), actor="fixture", occurred_at=at
    )
    g = manifest.runtime_generation_fingerprint
    registry.activate_for_new_work(target=g, expected_current=None, actor="fixture", occurred_at=at)
    registry.bind_new_work_exact(work_id, g, owner="research", actor="fixture", occurred_at=at)
    return {
        "candidate": candidate,
        "draft": draft.to_dict(),
        "revision": revision.to_dict(),
        "generation": g,
        "runtime_root": str(root),
        "installation": str(installation),
        "algorithm_artifact": artifact,
        "executor_sha256": native_manifest.artifact_sha256,
        "core_execution_fingerprint": core.fingerprint,
    }
