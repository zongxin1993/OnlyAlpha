from __future__ import annotations

import hashlib
import struct
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from onlyalpha_runtime_generation_manager import OnlyLocalImmutableArtifactStore, OnlyRuntimeGenerationBuilder

from onlyalpha.quant_assets import OnlyQuantAssetCatalogGeneration
from onlyalpha.runtime.generation import (
    OnlyArtifactSourceProvenanceAuthority,
    OnlyDistributionArtifactManifest,
    OnlyDistributionArtifactRole,
)


def _elf(machine: int = 183) -> bytes:
    # A controlled ELF64 header, not evidence of a loadable program or Rust compilation.
    return struct.pack(
        "<16sHHIQQQIHHHHHH", b"\x7fELF\x02\x01\x01" + b"\0" * 9, 3, machine, 1, 0, 0, 0, 0, 64, 56, 0, 64, 0, 0
    )


def _native(content: bytes, target: str = "aarch64-unknown-linux-gnu") -> OnlyDistributionArtifactManifest:
    return OnlyDistributionArtifactManifest(
        role=OnlyDistributionArtifactRole.SUPPORT,
        source_provenance_authority=OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
        source_repository="onlyalpha",
        source_revision="1" * 40,
        distribution_name="onlyalpha-kernel",
        distribution_version="0.10.3",
        artifact_logical_name=f"onlyalpha_kernel-0.10.3-{target}.elf",
        artifact_sha256=hashlib.sha256(content).hexdigest(),
        artifact_size=len(content),
    )


@pytest.mark.parametrize("target,machine", [("aarch64-unknown-linux-gnu", 183), ("x86_64-unknown-linux-gnu", 62)])
def test_native_diagnostic_artifact_roundtrips_exactly_after_store_restart(
    tmp_path: Path, target: str, machine: int
) -> None:
    content = _elf(machine)
    manifest = _native(content, target)
    assert manifest.native_target == target
    assert OnlyDistributionArtifactManifest.from_dict(manifest.to_dict()) == manifest
    store = OnlyLocalImmutableArtifactStore(tmp_path)
    path = store.put_once(manifest, content)
    assert path.name == "artifact.elf"
    assert path.stat().st_mode & 0o111 == 0
    restarted = OnlyLocalImmutableArtifactStore(tmp_path)
    assert restarted.fetch_exact(manifest.artifact_sha256) == (manifest, content)
    assert restarted.manifests() == (manifest,)
    assert restarted.put_once(manifest, content) == path
    with pytest.raises(ValueError, match="MANIFEST_CONFLICT"):
        restarted.put_once(replace(manifest, source_revision="2" * 40), content)
    assert restarted.fetch_exact(manifest.artifact_sha256) == (manifest, content)
    path.write_bytes(b"tamper")
    with pytest.raises(ValueError, match="ARTIFACT_MISMATCH"):
        restarted.fetch_exact(manifest.artifact_sha256)


@pytest.mark.parametrize(
    "changes",
    [
        {"role": OnlyDistributionArtifactRole.CORE},
        {"distribution_name": "other"},
        {"source_provenance_authority": OnlyArtifactSourceProvenanceAuthority.EXTERNAL_RELEASE},
        {"artifact_logical_name": "onlyalpha_kernel-0.10.3-x86_64-pc-windows-msvc.elf"},
        {"artifact_logical_name": "onlyalpha_kernel-0.10.3-aarch64-unknown-linux-musl.elf"},
        {"artifact_logical_name": "onlyalpha_kernel-0.10.3-extra-aarch64-unknown-linux-gnu.elf"},
        {"artifact_logical_name": "onlyalpha_kernel-0.10.3-aarch64-unknown-linux-gnu.ELF"},
        {"tested_core_execution_fingerprint": "a" * 64},
    ],
)
def test_native_manifest_cannot_grant_runtime_authority_or_guess_a_target(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="ARTIFACT_MANIFEST_INVALID"):
        replace(_native(_elf()), **changes)


@pytest.mark.parametrize(
    "content",
    [
        b"not ELF",
        _elf(62),
        _elf()[:63],
        b"\x7fELF\x01" + _elf()[5:],
        b"\x7fELF\x02\x02" + _elf()[6:],
        _elf()[:16] + b"\x01\x00" + _elf()[18:],
        _elf()[:20] + b"\x02\x00\x00\x00" + _elf()[24:],
    ],
)
def test_native_target_header_is_checked_even_when_hash_and_size_match(tmp_path: Path, content: bytes) -> None:
    store = OnlyLocalImmutableArtifactStore(tmp_path)
    with pytest.raises(ValueError, match="ARTIFACT_MISMATCH"):
        store.put_once(_native(content), content)
    assert not tuple(tmp_path.rglob("manifest.json"))


def test_native_artifacts_never_enter_python_generation_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _native(_elf())
    store = OnlyLocalImmutableArtifactStore(tmp_path / "store")
    store.put_once(manifest, _elf())
    builder = OnlyRuntimeGenerationBuilder(store, Path(sys.executable))

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("native diagnostic artifact reached process execution")

    monkeypatch.setattr("onlyalpha_runtime_generation_manager.builder.subprocess.run", forbidden)
    environment = tmp_path / "environment"
    with pytest.raises(ValueError, match="NATIVE_DIAGNOSTIC_NOT_INSTALLABLE"):
        builder.build(
            artifacts=(manifest,), expected_catalog=OnlyQuantAssetCatalogGeneration(()), environment_root=environment
        )
    assert not environment.exists()


def test_rejected_native_historical_generation_preserves_existing_environment(tmp_path: Path) -> None:
    from onlyalpha.runtime.generation import (
        OnlyCoreExecutionIdentity,
        OnlyRuntimeGenerationManifest,
        OnlyRuntimeProviderBinding,
    )

    content = _elf()
    native = _native(content)
    wheel_bytes = b"controlled wheel fixture"
    wheel = replace(
        native,
        role=OnlyDistributionArtifactRole.CORE,
        artifact_logical_name="onlyalpha_kernel-0.10.3-py3-none-any.whl",
        artifact_sha256=hashlib.sha256(wheel_bytes).hexdigest(),
        artifact_size=len(wheel_bytes),
    )
    store = OnlyLocalImmutableArtifactStore(tmp_path / "store")
    store.put_once(wheel, wheel_bytes)
    store.put_once(native, content)
    generation = OnlyRuntimeGenerationManifest(
        OnlyCoreExecutionIdentity("onlyalpha-kernel", "0.10.3", wheel.artifact_sha256),
        (wheel.manifest_fingerprint, native.manifest_fingerprint),
        (wheel.artifact_sha256, native.artifact_sha256),
        (OnlyRuntimeProviderBinding("fixture", "1", "a" * 64, wheel.artifact_sha256),),
        "b" * 64,
        (),
    )
    environment = tmp_path / "existing-environment"
    environment.mkdir()
    sentinel = environment / "retained.txt"
    sentinel.write_text("existing history")
    builder = OnlyRuntimeGenerationBuilder(store, Path(sys.executable))
    with pytest.raises(ValueError, match="NATIVE_DIAGNOSTIC_NOT_INSTALLABLE"):
        builder.rebuild_validated(expected_manifest=generation, environment_root=environment)
    assert sentinel.read_text() == "existing history"


@pytest.mark.parametrize("competing_creation", [False, True])
def test_historical_cleanup_only_removes_environment_claimed_by_this_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, competing_creation: bool
) -> None:
    from onlyalpha.runtime.generation import (
        OnlyCoreExecutionIdentity,
        OnlyRuntimeGenerationManifest,
        OnlyRuntimeProviderBinding,
    )

    content = b"controlled wheel fixture"
    wheel = replace(
        _native(content),
        role=OnlyDistributionArtifactRole.CORE,
        artifact_logical_name="onlyalpha_kernel-0.10.3-py3-none-any.whl",
    )
    store = OnlyLocalImmutableArtifactStore(tmp_path / "store")
    store.put_once(wheel, content)
    generation = OnlyRuntimeGenerationManifest(
        OnlyCoreExecutionIdentity("onlyalpha-kernel", "0.10.3", wheel.artifact_sha256),
        (wheel.manifest_fingerprint,),
        (wheel.artifact_sha256,),
        (OnlyRuntimeProviderBinding("fixture", "1", "a" * 64, wheel.artifact_sha256),),
        "b" * 64,
        (),
    )
    environment = tmp_path / "shared" / "environment"
    sentinel = environment / "retained.txt"
    real_mkdir = Path.mkdir

    def mkdir(path: Path, *args: object, **kwargs: object) -> None:
        real_mkdir(path, *args, **kwargs)
        if competing_creation and path == environment.parent:
            real_mkdir(environment)
            sentinel.write_text("owned by competing invocation")

    def fail_construction(*args: object, **kwargs: object) -> None:
        if not environment.exists():
            real_mkdir(environment)
        if not competing_creation:
            sentinel.write_text("partially constructed by this invocation")
        raise OSError("controlled construction failure")

    monkeypatch.setattr(Path, "mkdir", mkdir)
    monkeypatch.setattr("onlyalpha_runtime_generation_manager.builder.subprocess.run", fail_construction)
    builder = OnlyRuntimeGenerationBuilder(store, Path(sys.executable))
    with pytest.raises(OSError):
        builder.rebuild_validated(expected_manifest=generation, environment_root=environment)
    if competing_creation:
        assert sentinel.read_text() == "owned by competing invocation"
    else:
        assert not environment.exists()
