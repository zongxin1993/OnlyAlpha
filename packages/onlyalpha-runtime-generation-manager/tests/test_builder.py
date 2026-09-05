from __future__ import annotations

import hashlib
import subprocess
import sys
import zipfile
from dataclasses import replace
from importlib import metadata
from pathlib import Path

import pytest
from onlyalpha_example_strategies.provider import quant_asset_provider
from onlyalpha_runtime_generation_manager import (
    OnlyLocalImmutableArtifactStore,
    OnlyRuntimeGenerationBuilder,
)

from onlyalpha.quant_assets import (
    OnlyQuantAssetCatalogGeneration,
    only_quant_asset_distribution_artifact_manifest,
)
from onlyalpha.runtime.generation import (
    OnlyCoreExecutionIdentity,
    OnlyDistributionArtifactManifest,
    OnlyDistributionArtifactRole,
)


def _build_wheel(project: Path, output: Path) -> Path:
    completed = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(output), str(project)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stdout + completed.stderr)
    wheels = tuple(output.glob("*.whl"))
    assert len(wheels) == 1
    return wheels[0]


def _installed_distribution_wheel(name: str, output: Path) -> Path:
    distribution = metadata.distribution(name)
    wheel_metadata = distribution.read_text("WHEEL")
    assert wheel_metadata is not None
    tag = next(line.removeprefix("Tag: ") for line in wheel_metadata.splitlines() if line.startswith("Tag: "))
    normalized = name.replace("-", "_")
    target = output / f"{normalized}-{distribution.version}-{tag}.whl"
    output.mkdir(parents=True)
    files = distribution.files
    assert files is not None
    included = tuple(
        item
        for item in files
        if item.parts
        and (item.parts[0] == normalized or item.parts[0].startswith(f"{normalized}-{distribution.version}.dist-info"))
    )
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in sorted(included, key=str):
            content = Path(distribution.locate_file(relative)).read_bytes()
            info = zipfile.ZipInfo(str(relative), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)
    return target


def test_builder_installs_exact_public_example_in_clean_environment_and_is_deterministic(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[3]
    core_wheel = _build_wheel(repository, tmp_path / "core-wheel")
    strategy_wheel = _build_wheel(
        repository / "examples/onlyalpha-example-strategies",
        tmp_path / "strategy-wheel",
    )
    core_bytes = core_wheel.read_bytes()
    core_artifact = OnlyDistributionArtifactManifest(
        role=OnlyDistributionArtifactRole.CORE,
        source_repository="OnlyAlpha",
        source_revision="1" * 40,
        distribution_name="onlyalpha",
        distribution_version="0.9.9",
        artifact_logical_name=core_wheel.name,
        artifact_sha256=hashlib.sha256(core_bytes).hexdigest(),
        artifact_size=len(core_bytes),
    )
    core_identity = OnlyCoreExecutionIdentity(
        core_artifact.distribution_name,
        core_artifact.distribution_version,
        core_artifact.artifact_sha256,
    )
    provider = quant_asset_provider()
    strategy_bytes = strategy_wheel.read_bytes()
    strategy_artifact = only_quant_asset_distribution_artifact_manifest(
        source_repository="OnlyAlpha-example-strategies",
        source_revision="2" * 40,
        artifact_logical_name=strategy_wheel.name,
        artifact_bytes=strategy_bytes,
        tested_core_execution_fingerprint=core_identity.fingerprint,
        provider=provider,
    )
    artifacts = (core_artifact, strategy_artifact)
    store = OnlyLocalImmutableArtifactStore(tmp_path / "artifacts")
    store.put_once(core_artifact, core_bytes)
    store.put_once(strategy_artifact, strategy_bytes)
    builder = OnlyRuntimeGenerationBuilder(store, Path(sys.executable))
    catalog = OnlyQuantAssetCatalogGeneration((provider,))
    first = builder.build(artifacts=artifacts, expected_catalog=catalog, environment_root=tmp_path / "runtime-a")
    second = builder.build(artifacts=artifacts, expected_catalog=catalog, environment_root=tmp_path / "runtime-b")
    assert first == second
    assert first.catalog_generation_fingerprint == catalog.generation_fingerprint
    assert first.runtime_generation_fingerprint == second.runtime_generation_fingerprint


def test_catalog_mismatch_never_produces_a_generation(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[3]
    core_wheel = _build_wheel(repository, tmp_path / "core-wheel")
    strategy_wheel = _build_wheel(
        repository / "examples/onlyalpha-example-strategies",
        tmp_path / "strategy-wheel",
    )
    core_bytes = core_wheel.read_bytes()
    core_artifact = OnlyDistributionArtifactManifest(
        role=OnlyDistributionArtifactRole.CORE,
        source_repository="OnlyAlpha",
        source_revision="1" * 40,
        distribution_name="onlyalpha",
        distribution_version="0.9.9",
        artifact_logical_name=core_wheel.name,
        artifact_sha256=hashlib.sha256(core_bytes).hexdigest(),
        artifact_size=len(core_bytes),
    )
    provider = quant_asset_provider()
    strategy_bytes = strategy_wheel.read_bytes()
    strategy_artifact = only_quant_asset_distribution_artifact_manifest(
        source_repository="OnlyAlpha-example-strategies",
        source_revision="2" * 40,
        artifact_logical_name=strategy_wheel.name,
        artifact_bytes=strategy_bytes,
        tested_core_execution_fingerprint=OnlyCoreExecutionIdentity(
            "onlyalpha", "0.9.9", core_artifact.artifact_sha256
        ).fingerprint,
        provider=provider,
    )
    store = OnlyLocalImmutableArtifactStore(tmp_path / "artifacts")
    store.put_once(core_artifact, core_bytes)
    store.put_once(strategy_artifact, strategy_bytes)
    with pytest.raises(ValueError, match="RUNTIME_GENERATION_CATALOG_MISMATCH"):
        OnlyRuntimeGenerationBuilder(store, Path(sys.executable)).build(
            artifacts=(core_artifact, strategy_artifact),
            expected_catalog=OnlyQuantAssetCatalogGeneration(()),
            environment_root=tmp_path / "rejected-runtime",
        )
    assert not (tmp_path / "rejected-runtime").exists()


def test_builder_rejects_duplicate_distribution_identity_before_environment_creation(tmp_path: Path) -> None:
    first_bytes = b"first-wheel"
    second_bytes = b"second-wheel"
    common = {
        "source_repository": "OnlyAlpha",
        "source_revision": "1" * 40,
        "distribution_name": "onlyalpha",
        "distribution_version": "0.9.9",
        "artifact_logical_name": "onlyalpha-0.9.9-py3-none-any.whl",
    }
    core = OnlyDistributionArtifactManifest(
        role=OnlyDistributionArtifactRole.CORE,
        artifact_sha256=hashlib.sha256(first_bytes).hexdigest(),
        artifact_size=len(first_bytes),
        **common,
    )
    duplicate = OnlyDistributionArtifactManifest(
        role=OnlyDistributionArtifactRole.SUPPORT,
        artifact_sha256=hashlib.sha256(second_bytes).hexdigest(),
        artifact_size=len(second_bytes),
        **common,
    )
    store = OnlyLocalImmutableArtifactStore(tmp_path / "artifacts")
    store.put_once(core, first_bytes)
    store.put_once(duplicate, second_bytes)
    environment = tmp_path / "runtime"
    with pytest.raises(ValueError, match="RUNTIME_GENERATION_ARTIFACT_MISMATCH"):
        OnlyRuntimeGenerationBuilder(store, Path(sys.executable)).build(
            artifacts=(core, duplicate),
            expected_catalog=OnlyQuantAssetCatalogGeneration(()),
            environment_root=environment,
        )
    assert not environment.exists()


def test_builder_clean_installs_public_l3_example_with_exact_support_artifact(tmp_path: Path) -> None:
    from onlyalpha_example_alpha.provider import quant_asset_provider as alpha_provider

    repository = Path(__file__).resolve().parents[3]
    core_wheel = _build_wheel(repository, tmp_path / "core-wheel")
    alpha_wheel = _build_wheel(repository / "examples/onlyalpha-example-alpha", tmp_path / "alpha-wheel")
    pyarrow_wheel = _installed_distribution_wheel("pyarrow", tmp_path / "support-wheel")
    core_bytes = core_wheel.read_bytes()
    core_artifact = OnlyDistributionArtifactManifest(
        role=OnlyDistributionArtifactRole.CORE,
        source_repository="OnlyAlpha",
        source_revision="1" * 40,
        distribution_name="onlyalpha",
        distribution_version="0.9.9",
        artifact_logical_name=core_wheel.name,
        artifact_sha256=hashlib.sha256(core_bytes).hexdigest(),
        artifact_size=len(core_bytes),
    )
    core_identity = OnlyCoreExecutionIdentity("onlyalpha", "0.9.9", core_artifact.artifact_sha256)
    provider = alpha_provider()
    alpha_bytes = alpha_wheel.read_bytes()
    alpha_artifact = only_quant_asset_distribution_artifact_manifest(
        source_repository="OnlyAlpha-example-alpha",
        source_revision="2" * 40,
        artifact_logical_name=alpha_wheel.name,
        artifact_bytes=alpha_bytes,
        tested_core_execution_fingerprint=core_identity.fingerprint,
        provider=provider,
    )
    support_bytes = pyarrow_wheel.read_bytes()
    support_artifact = OnlyDistributionArtifactManifest(
        role=OnlyDistributionArtifactRole.SUPPORT,
        source_repository="Apache-Arrow",
        source_revision="pyarrow-25.0.0",
        distribution_name="pyarrow",
        distribution_version=metadata.version("pyarrow"),
        artifact_logical_name=pyarrow_wheel.name,
        artifact_sha256=hashlib.sha256(support_bytes).hexdigest(),
        artifact_size=len(support_bytes),
    )
    store = OnlyLocalImmutableArtifactStore(tmp_path / "artifacts")
    for manifest, content in (
        (core_artifact, core_bytes),
        (alpha_artifact, alpha_bytes),
        (support_artifact, support_bytes),
    ):
        store.put_once(manifest, content)
    generation = OnlyRuntimeGenerationBuilder(store, Path(sys.executable)).build(
        artifacts=(core_artifact, alpha_artifact, support_artifact),
        expected_catalog=OnlyQuantAssetCatalogGeneration((provider,)),
        environment_root=tmp_path / "runtime",
    )
    assert {item.provider_id for item in generation.providers} == {"example.alpha.library"}
    assert {item.backend for item in generation.implementations} == {"RESEARCH", "TRADING"}

    changed_implementation = replace(
        alpha_artifact.implementations[0],
        implementation_fingerprint=(
            "f" * 64 if alpha_artifact.implementations[0].implementation_fingerprint != "f" * 64 else "e" * 64
        ),
    )
    mismatched_artifact = replace(
        alpha_artifact,
        implementations=(changed_implementation, *alpha_artifact.implementations[1:]),
    )
    mismatch_store = OnlyLocalImmutableArtifactStore(tmp_path / "mismatch-artifacts")
    for manifest, content in (
        (core_artifact, core_bytes),
        (mismatched_artifact, alpha_bytes),
        (support_artifact, support_bytes),
    ):
        mismatch_store.put_once(manifest, content)
    with pytest.raises(ValueError, match="RUNTIME_GENERATION_IMPLEMENTATION_MISMATCH"):
        OnlyRuntimeGenerationBuilder(mismatch_store, Path(sys.executable)).build(
            artifacts=(core_artifact, mismatched_artifact, support_artifact),
            expected_catalog=OnlyQuantAssetCatalogGeneration((provider,)),
            environment_root=tmp_path / "mismatched-runtime",
        )
    assert not (tmp_path / "mismatched-runtime").exists()
