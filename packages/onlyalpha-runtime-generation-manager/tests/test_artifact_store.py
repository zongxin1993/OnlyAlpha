import json
from dataclasses import replace
from pathlib import Path

import pytest
from onlyalpha_runtime_generation_manager import OnlyLocalImmutableArtifactStore

from onlyalpha.quant_assets import (
    ONLY_PRIVATE_ALPHA_API_V1,
    OnlyPrivateAlphaDraft,
    OnlyPrivateAlphaRevision,
    OnlyPrivateAlphaSourceArtifactManifestV1,
    only_validate_private_alpha_revision,
)
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


def test_private_alpha_source_artifact_is_native_immutable_and_tamper_closed(tmp_path: Path) -> None:
    revision = OnlyPrivateAlphaRevision.from_draft(
        OnlyPrivateAlphaDraft(
            alpha_id="private.alpha.store",
            semantic_version="1",
            source_text="def calculate(api, inputs, parameters):\n    return inputs\n",
            alpha_api_version=1,
            alpha_api_contract_fingerprint=ONLY_PRIVATE_ALPHA_API_V1.api_contract_fingerprint,
            input_contract={},
            parameter_contract={},
            output_contract={},
            description="",
            economic_rationale="",
            category="test",
        )
    )
    artifact, source = OnlyPrivateAlphaSourceArtifactManifestV1.materialize(
        revision, only_validate_private_alpha_revision(revision)
    )
    store = OnlyLocalImmutableArtifactStore(tmp_path)
    path = store.put_private_alpha_source(artifact, source)
    assert path.name == "source.py"
    assert store.fetch_private_alpha_source(artifact.source_artifact_fingerprint) == (artifact, source)
    path.write_bytes(b"tamper")
    with pytest.raises(ValueError, match="PRIVATE_ALPHA_SOURCE_ARTIFACT_MISMATCH"):
        store.fetch_private_alpha_source(artifact.source_artifact_fingerprint)
    path.write_bytes(source)
    _, manifest_path = store._private_alpha_paths(artifact.source_artifact_fingerprint)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    del payload["source_artifact_fingerprint"]
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="PRIVATE_ALPHA_SOURCE_ARTIFACT_MISMATCH"):
        store.fetch_private_alpha_source(artifact.source_artifact_fingerprint)
