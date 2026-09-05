from dataclasses import replace
from pathlib import Path

import pytest
from onlyalpha_runtime_generation_manager import OnlyLocalImmutableArtifactStore

from onlyalpha.runtime.generation import (
    OnlyArtifactSourceProvenanceAuthority,
    OnlyDistributionArtifactManifest,
    OnlyDistributionArtifactRole,
)


def _manifest(content: bytes) -> OnlyDistributionArtifactManifest:
    import hashlib

    return OnlyDistributionArtifactManifest(
        role=OnlyDistributionArtifactRole.SUPPORT,
        source_provenance_authority=OnlyArtifactSourceProvenanceAuthority.EXTERNAL_RELEASE,
        source_repository="support-distribution",
        source_revision="1" * 40,
        distribution_name="support-distribution",
        distribution_version="1.0",
        artifact_logical_name="support_distribution-1.0-py3-none-any.whl",
        artifact_sha256=hashlib.sha256(content).hexdigest(),
        artifact_size=len(content),
    )


def test_put_once_fetch_and_exact_byte_mismatch(tmp_path: Path) -> None:
    content = b"immutable wheel"
    manifest = _manifest(content)
    store = OnlyLocalImmutableArtifactStore(tmp_path)
    assert store.put_once(manifest, content) == store.put_once(manifest, content)
    assert store.fetch_exact(manifest.artifact_sha256) == (manifest, content)
    with pytest.raises(ValueError, match="RUNTIME_GENERATION_ARTIFACT_MISMATCH"):
        store.put_once(manifest, b"changed wheel")


def test_same_bytes_with_conflicting_manifest_does_not_overwrite(tmp_path: Path) -> None:
    content = b"immutable wheel"
    manifest = _manifest(content)
    store = OnlyLocalImmutableArtifactStore(tmp_path)
    store.put_once(manifest, content)
    changed = replace(manifest, source_revision="2" * 40)
    with pytest.raises(ValueError, match="RUNTIME_GENERATION_ARTIFACT_MANIFEST_CONFLICT"):
        store.put_once(changed, content)
    assert store.fetch_exact(manifest.artifact_sha256) == (manifest, content)


def test_corrupt_stored_bytes_fail_closed(tmp_path: Path) -> None:
    content = b"immutable wheel"
    manifest = _manifest(content)
    store = OnlyLocalImmutableArtifactStore(tmp_path)
    path = store.put_once(manifest, content)
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="RUNTIME_GENERATION_ARTIFACT_MISMATCH"):
        store.fetch_exact(manifest.artifact_sha256)
