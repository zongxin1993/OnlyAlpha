"""Disposable code copies retain native verification and per-case isolation."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from onlyalpha.application.search_generation_execution import OnlyHistoricalGenerationExecutionError
from tests.runtime_support.chart_execution_host import exact_host_environment as exact_host_environment
from tests.runtime_support.chart_execution_host import materialize_exact_host_environment

pytestmark = pytest.mark.integration


def registry_for(root: Path, built):
    from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry

    registry = OnlyRuntimeGenerationRegistry(root)
    now = datetime(2026, 10, 10, tzinfo=UTC)
    registry.prepare(built.manifest, actor="fixture", occurred_at=now)
    registry.admit_ready(built.validation_evidence, actor="fixture", occurred_at=now)
    registry.activate_for_new_work(
        expected_current=None, target=built.manifest.runtime_generation_fingerprint, actor="fixture", occurred_at=now
    )
    return registry


def test_copies_start_distinct_exact_workers_without_sharing_installed_files(exact_host_environment, tmp_path):
    builder, built, host_type, template = exact_host_environment
    generation = built.manifest.runtime_generation_fingerprint
    environments = [materialize_exact_host_environment(template, generation, tmp_path / name) for name in ("a", "b")]
    hosts = [
        host_type(registry=registry_for(tmp_path / f"registry-{index}", built), builder=builder, cache_root=env.parent)
        for index, env in enumerate(environments)
    ]
    try:
        workers = [host.acquire(generation) for host in hosts]
        assert workers[0].process.pid != workers[1].process.pid
        assert workers[0].handshake == workers[1].handshake
        assert workers[0].handshake.runtime_generation_fingerprint == generation
        for environment in environments:
            probe = subprocess.run(
                [
                    str(environment / "bin/python"),
                    "-I",
                    "-c",
                    "import json,sys,onlyalpha; print(json.dumps([sys.prefix,onlyalpha.__file__]))",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            prefix, origin = json.loads(probe.stdout)
            assert Path(prefix) == environment
            assert Path(origin).is_relative_to(environment)
        leaf = next(template.glob("lib/python*/site-packages/onlyalpha/__init__.py"))
        relative = leaf.relative_to(template)
        before = leaf.read_bytes()
        assert (environments[0] / relative).stat().st_ino != leaf.stat().st_ino
        (environments[0] / relative).chmod(0o600)
        (environments[0] / relative).write_bytes(b"# case-owned mutation\n")
        assert leaf.read_bytes() == before
        assert (environments[1] / relative).read_bytes() == before
    finally:
        for host in hosts:
            host.close()


def test_missing_wrong_generation_and_existing_destination_are_not_reused(exact_host_environment, tmp_path):
    _, built, _, template = exact_host_environment
    generation = built.manifest.runtime_generation_fingerprint
    with pytest.raises(AssertionError, match="exact host template required"):
        materialize_exact_host_environment(tmp_path / generation, generation, tmp_path / "missing")
    with pytest.raises(AssertionError, match="exact host template required"):
        materialize_exact_host_environment(template, "0" * 64, tmp_path / "wrong")
    destination = materialize_exact_host_environment(template, generation, tmp_path / "exists")
    marker = destination / "case-owned"
    marker.write_bytes(b"original")
    mode = destination.stat().st_mode
    with pytest.raises(FileExistsError):
        materialize_exact_host_environment(template, generation, destination.parent)
    assert marker.read_bytes() == b"original" and destination.stat().st_mode == mode


def test_copied_installed_leaf_corruption_is_rejected_by_native_host(exact_host_environment, tmp_path):
    builder, built, host_type, template = exact_host_environment
    generation = built.manifest.runtime_generation_fingerprint
    environment = materialize_exact_host_environment(template, generation, tmp_path / "cache")
    # A still-importable change must fail exact installed-byte verification.
    leaf = next(environment.glob("lib/python*/site-packages/onlyalpha/__init__.py"))
    leaf.chmod(0o600)
    leaf.write_bytes(leaf.read_bytes() + b"\n# installed leaf corruption\n")
    host = host_type(
        registry=registry_for(tmp_path / "registry", built), builder=builder, cache_root=environment.parent
    )
    try:
        with pytest.raises(OnlyHistoricalGenerationExecutionError):
            host.acquire(generation)
    finally:
        host.close()


def test_matching_directory_name_cannot_replace_complete_different_generation(exact_host_environment, tmp_path):
    from onlyalpha_plugin_indicators.provider import quant_asset_provider

    from onlyalpha.quant_assets import OnlyQuantAssetCatalogGeneration
    from onlyalpha.runtime.generation import OnlyArtifactSourceProvenanceAuthority, OnlyDistributionArtifactRole
    from tests.support.runtime_distribution_wheels import installed_distribution_wheel, plain_artifact

    builder, original, host_type, template = exact_host_environment
    wheel = installed_distribution_wheel("packaging", tmp_path / "support")
    support = plain_artifact(
        wheel,
        role=OnlyDistributionArtifactRole.SUPPORT,
        authority=OnlyArtifactSourceProvenanceAuthority.EXTERNAL_RELEASE,
        repository="packaging",
        revision="fixture",
    )
    builder.artifact_store.put_once(support, wheel.read_bytes())
    artifacts = tuple(builder.artifact_store.fetch_exact(value)[0] for value in original.manifest.artifact_sha256s)
    different = builder.build_validated(
        artifacts=(*artifacts, support),
        expected_catalog=OnlyQuantAssetCatalogGeneration((quant_asset_provider(),)),
        environment_root=tmp_path / "different-built",
    )
    generation = different.manifest.runtime_generation_fingerprint
    assert generation != original.manifest.runtime_generation_fingerprint
    environment = materialize_exact_host_environment(
        template, original.manifest.runtime_generation_fingerprint, tmp_path / "cache"
    )
    renamed = environment.with_name(generation)
    environment.rename(renamed)
    host = host_type(
        registry=registry_for(tmp_path / "registry", different), builder=builder, cache_root=renamed.parent
    )
    try:
        with pytest.raises(OnlyHistoricalGenerationExecutionError):
            host.acquire(generation)
    finally:
        host.close()


def test_external_symlink_is_rejected_without_changing_its_target(tmp_path):
    generation = "1" * 64
    template = tmp_path / "template" / generation
    template.mkdir(parents=True)
    external = tmp_path / "mutable-built"
    external.write_bytes(b"not an interpreter")
    (template / "external").symlink_to(external)
    mode = external.stat().st_mode
    with pytest.raises(AssertionError, match="external template symlink"):
        materialize_exact_host_environment(template, generation, tmp_path / "cache")
    assert external.read_bytes() == b"not an interpreter" and external.stat().st_mode == mode
    assert not (tmp_path / "cache" / generation).exists()


def test_partial_copy_failure_remains_failure_and_its_owned_directories_can_be_cleaned(tmp_path, monkeypatch):
    import shutil

    generation = "1" * 64
    template = tmp_path / "template" / generation
    template.mkdir(parents=True)
    template.chmod(0o555)

    def fail_copy(source, target, **kwargs):
        target.mkdir(parents=True)
        (target / "partial").mkdir()
        (target / "partial").chmod(0o555)
        raise OSError("injected copy failure")

    monkeypatch.setattr(shutil, "copytree", fail_copy)
    try:
        with pytest.raises(OSError, match="injected copy failure"):
            materialize_exact_host_environment(template, generation, tmp_path / "cache")
        assert (tmp_path / "cache" / generation / "partial").stat().st_mode & 0o200
    finally:
        template.chmod(0o755)
