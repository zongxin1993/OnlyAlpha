"""Offline reference-conformance closure; never a Shipping Product installation."""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

from onlyalpha_plugin_indicators.provider import quant_asset_provider as indicators
from onlyalpha_plugin_operators.provider import quant_asset_provider as operators
from onlyalpha_runtime_generation_manager import (
    OnlyLocalImmutableArtifactStore,
    OnlyRuntimeGenerationBuilder,
    OnlyRuntimeGenerationRegistry,
)
from onlyalpha_test_factor_provider.provider import quant_asset_provider as factors
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from onlyalpha.quant_assets import OnlyQuantAssetCatalogGeneration, only_quant_asset_distribution_artifact_manifest
from onlyalpha.runtime.generation import (
    OnlyArtifactSourceProvenanceAuthority,
    OnlyCoreExecutionIdentity,
    OnlyDistributionArtifactManifest,
    OnlyDistributionArtifactRole,
)
from tests.support.runtime_distribution_wheels import build_wheel, installed_distribution_wheel


@dataclass(frozen=True)
class NativeBacktestGeneration:
    authority: OnlyRuntimeGenerationRegistry
    environment: Path
    fingerprint: str


def build_native_backtest_generation(root: Path, executable: Path) -> NativeBacktestGeneration:
    repository = Path(__file__).resolve().parents[2]
    # Test prerequisites are built from this frozen source, never borrowed from another lane.
    from scripts.rust_kernel_check import compiler_environment, prepare_cargo_home

    target = {"aarch64": "aarch64-unknown-linux-gnu", "x86_64": "x86_64-unknown-linux-gnu"}[platform.machine()]
    target_dir = repository / "test-results/rust-kernel/target"
    expected = target_dir / target / "release/onlyalpha-backtest-runtime"
    if executable != expected:
        raise ValueError("Native Backtest fixture must use the current canonical build output")
    env = compiler_environment(os.environ, target_dir)
    env["RUSTUP_TOOLCHAIN"] = tomllib.loads((repository / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
    prepare_cargo_home(Path("/usr/local/cargo/registry"), Path(env["CARGO_HOME"]))
    subprocess.run(
        [
            "cargo",
            "build",
            "--release",
            "--frozen",
            "--offline",
            "--target",
            target,
            "-j1",
            "-p",
            "onlyalpha-backtest",
            "--bin",
            "onlyalpha-backtest-runtime",
        ],
        cwd=repository,
        env=env,
        check=True,
    )
    projects = {"onlyalpha": repository}
    for project in (
        *repository.glob("packages/*"),
        *repository.glob("plugs/*"),
        repository / "test-data/runtime_factor_provider",
    ):
        path = project / "pyproject.toml"
        if path.is_file():
            projects[canonicalize_name(tomllib.loads(path.read_text())["project"]["name"])] = project
    selected: set[str] = set()
    pending = [
        "onlyalpha-runtime-generation-manager",
        "onlyalpha-test-factor-provider",
        "onlyalpha-calculation-worker",
        "psycopg-binary",
        "packaging",
    ]
    while pending:
        name = canonicalize_name(pending.pop())
        if name in selected:
            continue
        selected.add(name)
        distribution = metadata.distribution(name)
        for raw in distribution.requires or ():
            requirement = Requirement(raw)
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                pending.append(requirement.name)
    # The reference test exercises the real sealed registry and native journal.
    # Its private installation advertises only the exact verified calculation
    # context. No maintained distribution re-enables a Python business service,
    # and this technical fixture is not Product/UI acceptance evidence.
    manager = "onlyalpha-runtime-generation-manager"
    staged = root / "build-source" / manager
    shutil.copytree(projects[manager], staged, ignore=shutil.ignore_patterns("build", "__pycache__", "*.egg-info"))
    staged_manifest = staged / "pyproject.toml"
    # Only this disposable copy is writable; the canonical frozen source stays read-only.
    staged_manifest.chmod(staged_manifest.stat().st_mode | 0o200)
    with staged_manifest.open("a") as manifest:
        manifest.write(
            '\n[project.entry-points."onlyalpha.calculation_generation_context"]\n'
            'reference-context = "onlyalpha_runtime_generation_manager.entrypoint:calculation_generation_context"\n'
        )
    projects[manager] = staged
    wheels = {
        name: build_wheel(projects[name], root / "wheels" / name)
        if name in projects
        else installed_distribution_wheel(name, root / "wheels" / name)
        for name in sorted(selected)
    }

    def plain(name: str, role: OnlyDistributionArtifactRole) -> OnlyDistributionArtifactManifest:
        wheel = wheels[name]
        content = wheel.read_bytes()
        return OnlyDistributionArtifactManifest(
            role,
            OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT
            if name.startswith("onlyalpha")
            else OnlyArtifactSourceProvenanceAuthority.EXTERNAL_RELEASE,
            name,
            "1" * 40,
            name,
            metadata.version(name),
            wheel.name,
            hashlib.sha256(content).hexdigest(),
            len(content),
        )

    core = plain("onlyalpha", OnlyDistributionArtifactRole.CORE)
    identity = OnlyCoreExecutionIdentity(core.distribution_name, core.distribution_version, core.artifact_sha256)
    catalog = OnlyQuantAssetCatalogGeneration((indicators(), operators(), factors()))
    provider_names = {canonicalize_name(item.manifest.distribution_name) for item in catalog.providers}
    artifacts = [core]
    for provider in catalog.providers:
        wheel = wheels[canonicalize_name(provider.manifest.distribution_name)]
        artifacts.append(
            only_quant_asset_distribution_artifact_manifest(
                source_repository=provider.manifest.distribution_name,
                source_revision="1" * 40,
                artifact_logical_name=wheel.name,
                artifact_bytes=wheel.read_bytes(),
                tested_core_execution_fingerprint=identity.fingerprint,
                provider=provider,
            )
        )
    artifacts.extend(
        plain(name, OnlyDistributionArtifactRole.SUPPORT) for name in sorted(selected - provider_names - {"onlyalpha"})
    )
    probe = __import__("json").loads(__import__("subprocess").check_output([str(executable), "--describe"], text=True))
    content = executable.read_bytes()
    native = OnlyDistributionArtifactManifest(
        role=OnlyDistributionArtifactRole.BACKTEST_RUNTIME,
        source_provenance_authority=OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
        source_repository="OnlyAlpha",
        source_revision="1" * 40,
        distribution_name="onlyalpha-backtest-driver",
        distribution_version=probe["version"],
        artifact_logical_name=f"onlyalpha_backtest_driver-{probe['version']}-{probe['target']}.elf",
        artifact_sha256=hashlib.sha256(content).hexdigest(),
        artifact_size=len(content),
        tested_core_execution_fingerprint=identity.fingerprint,
    )
    artifacts.append(native)
    authority = OnlyRuntimeGenerationRegistry(root / "authority")
    store = OnlyLocalImmutableArtifactStore(authority.root / "artifacts")
    content_by_name = {wheel.name: wheel.read_bytes() for wheel in wheels.values()}
    content_by_name[native.artifact_logical_name] = content
    for artifact in artifacts:
        store.put_once(artifact, content_by_name[artifact.artifact_logical_name])
    environment = root / "host"
    validated = OnlyRuntimeGenerationBuilder(store, Path(sys.executable)).build_validated(
        artifacts=tuple(artifacts), expected_catalog=catalog, environment_root=environment
    )
    now = datetime(2026, 10, 21, tzinfo=UTC)
    authority.prepare(validated.manifest, actor="isolated-test-setup", occurred_at=now)
    authority.admit_ready(validated.validation_evidence, actor="isolated-test-validator", occurred_at=now)
    generation = validated.manifest.runtime_generation_fingerprint
    authority.activate_for_new_work(
        expected_current=None, target=generation, actor="isolated-test-operator", occurred_at=now
    )
    return NativeBacktestGeneration(authority, environment, generation)
