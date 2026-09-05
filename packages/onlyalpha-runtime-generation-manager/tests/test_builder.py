from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

import pytest
from onlyalpha_example_strategies.provider import quant_asset_provider
from onlyalpha_runtime_generation_manager import (
    OnlyHistoricalExecutableRuntimeGenerationResolver,
    OnlyLocalImmutableArtifactStore,
    OnlyRuntimeGenerationBuilder,
)
from onlyalpha_runtime_generation_manager.hosted import _verify_installed_wheel

from onlyalpha.calculation.artifact import only_calculation_distribution_artifact_manifest
from onlyalpha.quant_assets import (
    OnlyQuantAssetCatalogGeneration,
    only_quant_asset_distribution_artifact_manifest,
)
from onlyalpha.runtime.generation import (
    OnlyArtifactSourceProvenanceAuthority,
    OnlyCoreExecutionIdentity,
    OnlyDistributionArtifactManifest,
    OnlyDistributionArtifactRole,
)

NOW = datetime(2026, 9, 5, tzinfo=UTC)


def test_hosted_verification_fails_closed_for_unmapped_wheel_data_files(tmp_path: Path) -> None:
    wheel = tmp_path / "onlyalpha-0.9.9-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "onlyalpha-0.9.9.dist-info/METADATA",
            f"Name: onlyalpha\nVersion: {metadata.version('onlyalpha')}\n",
        )
        archive.writestr(
            "onlyalpha-0.9.9.dist-info/RECORD",
            "onlyalpha-0.9.9.data/data/unverified.txt,sha256=AA,1\n",
        )

    with pytest.raises(RuntimeError, match="RUNTIME_GENERATION_HOSTED_PROCESS_MISMATCH"):
        _verify_installed_wheel(wheel)


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
    tags = tuple(line.removeprefix("Tag: ") for line in wheel_metadata.splitlines() if line.startswith("Tag: "))
    tag = next((item for item in tags if item.startswith(("py3-", "py2.py3-"))), tags[0])
    normalized = name.replace("-", "_")
    target = output / f"{normalized}-{distribution.version}-{tag}.whl"
    output.mkdir(parents=True, exist_ok=True)
    files = distribution.files
    assert files is not None
    included = tuple(item for item in files if item.parts and item.parts[0] != "..")
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in sorted(included, key=str):
            content = Path(distribution.locate_file(relative)).read_bytes()
            info = zipfile.ZipInfo(str(relative), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)
    return target


def _plain_artifact(
    wheel: Path,
    *,
    role: OnlyDistributionArtifactRole,
    authority: OnlyArtifactSourceProvenanceAuthority,
    repository: str,
    revision: str,
) -> OnlyDistributionArtifactManifest:
    content = wheel.read_bytes()
    distribution = metadata.distribution(_wheel_distribution_name(wheel))
    return OnlyDistributionArtifactManifest(
        role=role,
        source_provenance_authority=authority,
        source_repository=repository,
        source_revision=revision,
        distribution_name=distribution.metadata["Name"],
        distribution_version=distribution.version,
        artifact_logical_name=wheel.name,
        artifact_sha256=hashlib.sha256(content).hexdigest(),
        artifact_size=len(content),
    )


def _wheel_distribution_name(wheel: Path) -> str:
    with zipfile.ZipFile(wheel) as archive:
        metadata_name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        content = archive.read(metadata_name).decode("utf-8")
    return next(line[6:] for line in content.splitlines() if line.startswith("Name: "))


def test_builder_installs_exact_public_example_in_clean_environment_and_is_deterministic(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[3]
    core_wheel = _build_wheel(repository, tmp_path / "core-wheel")
    manager_wheel = _build_wheel(
        repository / "packages/onlyalpha-runtime-generation-manager",
        tmp_path / "manager-wheel",
    )
    strategy_wheel = _build_wheel(
        repository / "examples/onlyalpha-example-strategies",
        tmp_path / "strategy-wheel",
    )
    pyarrow_wheel = _installed_distribution_wheel("pyarrow", tmp_path / "support-wheel")
    core_bytes = core_wheel.read_bytes()
    core_artifact = OnlyDistributionArtifactManifest(
        role=OnlyDistributionArtifactRole.CORE,
        source_provenance_authority=OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
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
    manager_bytes = manager_wheel.read_bytes()
    manager_artifact = OnlyDistributionArtifactManifest(
        role=OnlyDistributionArtifactRole.SUPPORT,
        source_provenance_authority=OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
        source_repository="OnlyAlpha",
        source_revision="3" * 40,
        distribution_name="onlyalpha-runtime-generation-manager",
        distribution_version="0.9.9",
        artifact_logical_name=manager_wheel.name,
        artifact_sha256=hashlib.sha256(manager_bytes).hexdigest(),
        artifact_size=len(manager_bytes),
    )
    pyarrow_artifact = _plain_artifact(
        pyarrow_wheel,
        role=OnlyDistributionArtifactRole.SUPPORT,
        authority=OnlyArtifactSourceProvenanceAuthority.EXTERNAL_RELEASE,
        repository="Apache-Arrow",
        revision=f"release-{metadata.version('pyarrow')}",
    )
    artifacts = (core_artifact, manager_artifact, strategy_artifact, pyarrow_artifact)
    store = OnlyLocalImmutableArtifactStore(tmp_path / "artifacts")
    store.put_once(core_artifact, core_bytes)
    store.put_once(manager_artifact, manager_bytes)
    store.put_once(strategy_artifact, strategy_bytes)
    store.put_once(pyarrow_artifact, pyarrow_wheel.read_bytes())
    builder = OnlyRuntimeGenerationBuilder(store, Path(sys.executable))
    catalog = OnlyQuantAssetCatalogGeneration((provider,))
    first = builder.build_validated(
        artifacts=artifacts, expected_catalog=catalog, environment_root=tmp_path / "runtime-a"
    )
    second = builder.build_validated(
        artifacts=artifacts, expected_catalog=catalog, environment_root=tmp_path / "runtime-b"
    )
    assert first == second
    assert first.manifest.catalog_generation_fingerprint == catalog.generation_fingerprint
    assert first.validation_evidence.verifies(first.manifest)
    assert first.manifest.runtime_generation_fingerprint == second.manifest.runtime_generation_fingerprint
    hosted = subprocess.run(
        [
            str(tmp_path / "runtime-a" / "bin" / "python"),
            "-I",
            "-c",
            "from pathlib import Path; import json; "
            "from onlyalpha.runtime.generation import OnlyRuntimeGenerationValidationEvidence; "
            "from onlyalpha_runtime_generation_manager.hosted import only_verify_hosted_runtime_generation; "
            "e=OnlyRuntimeGenerationValidationEvidence.from_dict(json.loads("
            "Path('onlyalpha-runtime-generation-validation.json').read_text())); "
            "only_verify_hosted_runtime_generation(e)",
        ],
        cwd=tmp_path / "runtime-a",
        capture_output=True,
        text=True,
        check=False,
    )
    assert hosted.returncode == 0, hosted.stdout + hosted.stderr
    installed_provider = next(
        (tmp_path / "runtime-b").glob("lib/python*/site-packages/onlyalpha_example_strategies/provider.py")
    )
    installed_provider.write_bytes(installed_provider.read_bytes() + b"\n")
    mismatched_host = subprocess.run(
        [
            str(tmp_path / "runtime-b" / "bin" / "python"),
            "-I",
            "-c",
            "from pathlib import Path; import json; "
            "from onlyalpha.runtime.generation import OnlyRuntimeGenerationValidationEvidence; "
            "from onlyalpha_runtime_generation_manager.hosted import only_verify_hosted_runtime_generation; "
            "e=OnlyRuntimeGenerationValidationEvidence.from_dict(json.loads("
            "Path('onlyalpha-runtime-generation-validation.json').read_text())); "
            "only_verify_hosted_runtime_generation(e)",
        ],
        cwd=tmp_path / "runtime-b",
        capture_output=True,
        text=True,
        check=False,
    )
    assert mismatched_host.returncode != 0
    assert "RUNTIME_GENERATION_HOSTED_PROCESS_MISMATCH" in mismatched_host.stderr

    class _HistoricalManifest:
        def resolve(self, revision, *, exact_generation_fingerprint=None):  # type: ignore[no-untyped-def]
            del revision
            assert exact_generation_fingerprint == first.manifest.runtime_generation_fingerprint
            return first.manifest

    reconstructed = OnlyHistoricalExecutableRuntimeGenerationResolver(  # type: ignore[arg-type]
        _HistoricalManifest(),
        builder,
    ).resolve(
        object(),  # type: ignore[arg-type]
        exact_generation_fingerprint=first.manifest.runtime_generation_fingerprint,
        environment_root=tmp_path / "historical-runtime",
    )
    assert reconstructed.manifest.runtime_generation_fingerprint == first.manifest.runtime_generation_fingerprint

    artifact_path, _ = store._paths(strategy_artifact.artifact_sha256)
    artifact_path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="HISTORICAL_IMPLEMENTATION_UNAVAILABLE"):
        OnlyHistoricalExecutableRuntimeGenerationResolver(  # type: ignore[arg-type]
            _HistoricalManifest(),
            builder,
        ).resolve(
            object(),  # type: ignore[arg-type]
            exact_generation_fingerprint=first.manifest.runtime_generation_fingerprint,
            environment_root=tmp_path / "corrupt-historical-runtime",
        )


def test_public_examples_execute_research_and_freeze_on_one_exact_runtime_generation(tmp_path: Path) -> None:
    from onlyalpha_example_alpha.provider import quant_asset_provider as alpha_provider
    from onlyalpha_example_strategies.provider import quant_asset_provider as strategy_provider
    from onlyalpha_plugin_indicators.provider import quant_asset_provider as indicator_provider
    from onlyalpha_plugin_operators.provider import quant_asset_provider as operator_provider
    from onlyalpha_plugin_targets.registration import registrations as target_registrations
    from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry

    repository = Path(__file__).resolve().parents[3]
    projects = {
        "onlyalpha": repository,
        "onlyalpha-runtime-generation-manager": repository / "packages/onlyalpha-runtime-generation-manager",
        "onlyalpha-example-alpha": repository / "examples/onlyalpha-example-alpha",
        "onlyalpha-example-strategies": repository / "examples/onlyalpha-example-strategies",
        "onlyalpha-plugin-operators": repository / "plugs/onlyalpha-plugin-operators",
        "onlyalpha-plugin-indicators": repository / "plugs/onlyalpha-plugin-indicators",
        "onlyalpha-plugin-targets": repository / "plugs/onlyalpha-plugin-targets",
    }
    wheels = {name: _build_wheel(project, tmp_path / "wheels" / name) for name, project in projects.items()}
    core_wheel = wheels["onlyalpha"]
    core_bytes = core_wheel.read_bytes()
    core_artifact = OnlyDistributionArtifactManifest(
        role=OnlyDistributionArtifactRole.CORE,
        source_provenance_authority=OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
        source_repository="OnlyAlpha",
        source_revision="1" * 40,
        distribution_name="onlyalpha",
        distribution_version=metadata.version("onlyalpha"),
        artifact_logical_name=core_wheel.name,
        artifact_sha256=hashlib.sha256(core_bytes).hexdigest(),
        artifact_size=len(core_bytes),
    )
    core_identity = OnlyCoreExecutionIdentity(
        core_artifact.distribution_name,
        core_artifact.distribution_version,
        core_artifact.artifact_sha256,
    )
    providers = (operator_provider(), indicator_provider(), alpha_provider(), strategy_provider())
    provider_wheels = {
        "onlyalpha.operator.library": wheels["onlyalpha-plugin-operators"],
        "onlyalpha.indicator.library": wheels["onlyalpha-plugin-indicators"],
        "example.alpha.library": wheels["onlyalpha-example-alpha"],
        "example.strategy.library": wheels["onlyalpha-example-strategies"],
    }
    quant_artifacts = tuple(
        only_quant_asset_distribution_artifact_manifest(
            source_repository=provider.manifest.distribution_name,
            source_revision="2" * 40,
            artifact_logical_name=provider_wheels[provider.manifest.provider_id].name,
            artifact_bytes=provider_wheels[provider.manifest.provider_id].read_bytes(),
            tested_core_execution_fingerprint=core_identity.fingerprint,
            provider=provider,
        )
        for provider in providers
    )
    target_wheel = wheels["onlyalpha-plugin-targets"]
    target_artifact = only_calculation_distribution_artifact_manifest(
        source_repository="OnlyAlpha",
        source_revision="3" * 40,
        distribution_name="onlyalpha-plugin-targets",
        distribution_version=metadata.version("onlyalpha-plugin-targets"),
        artifact_logical_name=target_wheel.name,
        artifact_bytes=target_wheel.read_bytes(),
        tested_core_execution_fingerprint=core_identity.fingerprint,
        registrations=target_registrations(),
    )
    manager_artifact = _plain_artifact(
        wheels["onlyalpha-runtime-generation-manager"],
        role=OnlyDistributionArtifactRole.SUPPORT,
        authority=OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
        repository="OnlyAlpha",
        revision="4" * 40,
    )
    support_wheels = tuple(
        _installed_distribution_wheel(name, tmp_path / "wheels" / "support")
        for name in (
            "pyarrow",
            "numpy",
            "pytest",
            "iniconfig",
            "packaging",
            "pluggy",
            "pygments",
            "hypothesis",
            "sortedcontainers",
            "pyyaml",
            "psycopg",
            "psycopg-binary",
        )
    )
    support_artifacts = tuple(
        _plain_artifact(
            wheel,
            role=OnlyDistributionArtifactRole.SUPPORT,
            authority=OnlyArtifactSourceProvenanceAuthority.EXTERNAL_RELEASE,
            repository=_wheel_distribution_name(wheel),
            revision=f"release-{metadata.version(_wheel_distribution_name(wheel))}",
        )
        for wheel in support_wheels
    )
    artifacts = (core_artifact, manager_artifact, target_artifact, *quant_artifacts, *support_artifacts)
    store = OnlyLocalImmutableArtifactStore(tmp_path / "artifact-store")
    content_by_name = {wheel.name: wheel.read_bytes() for wheel in (*wheels.values(), *support_wheels)}
    for artifact in artifacts:
        store.put_once(artifact, content_by_name[artifact.artifact_logical_name])

    validated = OnlyRuntimeGenerationBuilder(store, Path(sys.executable)).build_validated(
        artifacts=artifacts,
        expected_catalog=OnlyQuantAssetCatalogGeneration(providers),
        environment_root=tmp_path / "runtime",
    )
    authority_root = tmp_path / "authority"
    authority = OnlyRuntimeGenerationRegistry(authority_root)
    authority.prepare(validated.manifest, actor="operator", occurred_at=NOW)
    authority.admit_ready(validated.validation_evidence, actor="validator", occurred_at=NOW)
    generation = validated.manifest.runtime_generation_fingerprint
    authority.activate_for_new_work(
        expected_current=None,
        target=generation,
        actor="operator",
        occurred_at=NOW,
    )

    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "ONLYALPHA_EXACT_RUNTIME_GENERATION_FINGERPRINT": generation,
            "ONLYALPHA_EXACT_RUNTIME_GENERATION_AUTHORITY_ROOT": str(authority_root),
        }
    )
    conformance = repository / "tests/quant_assets/test_private_asset_contract_conformance.py"
    command = (
        "from pathlib import Path; import pytest; "
        "from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry; "
        f"a=OnlyRuntimeGenerationRegistry(Path({str(authority_root)!r})); "
        f"a.verify_hosted_generation({generation!r}); "
        f"raise SystemExit(pytest.main([{str(conformance)!r}, '-q', '-k', "
        "'installed_l3_l4_resolve_research_evidence_freeze_and_revision']))"
    )
    completed = subprocess.run(
        [str(tmp_path / "runtime" / "bin" / "python"), "-I", "-c", command],
        cwd=tmp_path / "runtime",
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    binding = authority.require_work_binding("00000000-0000-4000-8000-000000003000")
    assert binding.runtime_generation_fingerprint == generation


def test_catalog_mismatch_never_produces_a_generation(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[3]
    core_wheel = _build_wheel(repository, tmp_path / "core-wheel")
    strategy_wheel = _build_wheel(
        repository / "examples/onlyalpha-example-strategies",
        tmp_path / "strategy-wheel",
    )
    pyarrow_wheel = _installed_distribution_wheel("pyarrow", tmp_path / "support-wheel")
    core_bytes = core_wheel.read_bytes()
    core_artifact = OnlyDistributionArtifactManifest(
        role=OnlyDistributionArtifactRole.CORE,
        source_provenance_authority=OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
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
    pyarrow_artifact = _plain_artifact(
        pyarrow_wheel,
        role=OnlyDistributionArtifactRole.SUPPORT,
        authority=OnlyArtifactSourceProvenanceAuthority.EXTERNAL_RELEASE,
        repository="Apache-Arrow",
        revision=f"release-{metadata.version('pyarrow')}",
    )
    store = OnlyLocalImmutableArtifactStore(tmp_path / "artifacts")
    store.put_once(core_artifact, core_bytes)
    store.put_once(strategy_artifact, strategy_bytes)
    store.put_once(pyarrow_artifact, pyarrow_wheel.read_bytes())
    with pytest.raises(ValueError, match="RUNTIME_GENERATION_CATALOG_MISMATCH"):
        OnlyRuntimeGenerationBuilder(store, Path(sys.executable)).build(
            artifacts=(core_artifact, strategy_artifact, pyarrow_artifact),
            expected_catalog=OnlyQuantAssetCatalogGeneration(()),
            environment_root=tmp_path / "rejected-runtime",
        )
    assert not (tmp_path / "rejected-runtime").exists()


def test_builder_rejects_duplicate_distribution_identity_before_environment_creation(tmp_path: Path) -> None:
    first_bytes = b"first-wheel"
    second_bytes = b"second-wheel"
    common = {
        "source_provenance_authority": OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
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
        source_provenance_authority=OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
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
        source_provenance_authority=OnlyArtifactSourceProvenanceAuthority.EXTERNAL_RELEASE,
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
