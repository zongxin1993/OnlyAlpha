"""Receipt-less exact lookup, not scientific absence or execution permission."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from onlyalpha.research.artifact.errors import OnlyResearchArtifactError
from tests.research.artifact.test_calculation_v2 import _publication, _root

pytestmark = pytest.mark.contract


def _references(manifest):
    return {
        "result": manifest.result,
        "dataset": manifest.dataset,
        "calculations": manifest.calculations,
        "selected_evidence": manifest.selected_evidence,
        "retained_generation": manifest.retained_generation,
        "sealed_input": manifest.sealed_input,
    }


def _bytes(root):
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_exact_artifact_inspection_derives_pair_without_scan_write_or_acknowledgement(tmp_path, monkeypatch):
    publish, store, _, _, _, _ = _publication(tmp_path)
    artifact = publish()
    before = _bytes(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("inspection scanned, wrote or acknowledged")

    with monkeypatch.context() as scope:
        scope.setattr(store, "_acknowledge", forbidden)
        scope.setattr(store, "_publish_materialized", forbidden)
        scope.setattr("onlyalpha.research.artifact.calculation_v2_store.os.fsync", forbidden)
        scope.setattr(Path, "rglob", forbidden)
        inspected = store.load_exact_for_publication(**_references(artifact.manifest))
        assert inspected.manifest == artifact.manifest
    assert _bytes(tmp_path) == before


@pytest.mark.parametrize("encoding", ["snappy", None])
def test_exact_artifact_lookup_uses_existing_logical_identity_not_encoding(tmp_path, encoding):
    publish, store, _, _, _, _ = _publication(tmp_path)
    store._compression = encoding
    artifact = publish()
    kwargs = _references(artifact.manifest)
    # Copied partitions have different physical hashes, but original owning
    # manifests and complete selected proof identify the same portable package.
    kwargs["dataset"] = replace(
        artifact.manifest.dataset,
        partitions=tuple(replace(item, byte_sha256="a" * 64) for item in artifact.manifest.dataset.partitions),
    )
    inspected = store.load_exact_for_publication(**kwargs)
    assert inspected.manifest == artifact.manifest


@pytest.mark.parametrize(
    "field",
    ["result", "dataset", "calculations", "selected_evidence", "retained_generation", "sealed_input"],
)
def test_exact_artifact_inspection_rejects_missing_mandatory_context(tmp_path, field):
    publish, store, _, _, _, _ = _publication(tmp_path)
    artifact = publish()
    kwargs = _references(artifact.manifest)
    kwargs[field] = None
    before = _bytes(tmp_path)
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_CORRUPT"):
        store.load_exact_for_publication(**kwargs)
    assert _bytes(tmp_path) == before


@pytest.mark.parametrize("selection", ["empty", "duplicate", "missing_runtime", "wrong_result"])
def test_exact_artifact_inspection_never_uses_incomplete_or_wrong_selected_proof(tmp_path, selection):
    publish, store, _, _, _, _ = _publication(tmp_path)
    artifact = publish()
    kwargs = _references(artifact.manifest)
    evidence = artifact.manifest.selected_evidence[0]
    kwargs["selected_evidence"] = {
        "empty": (),
        "duplicate": (evidence, evidence),
        "missing_runtime": (replace(evidence, runtime_execution_provenance=None),),
        "wrong_result": (replace(evidence, calculation_result_fingerprint="f" * 64),),
    }[selection]
    before = _bytes(tmp_path)
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_CORRUPT"):
        store.load_exact_for_publication(**kwargs)
    assert _bytes(tmp_path) == before


def test_exact_artifact_inspection_never_selects_shared_result_from_different_generation(tmp_path):
    from onlyalpha.distribution import (
        OnlyArtifactSourceProvenanceAuthority,
        OnlyDistributionArtifactManifest,
        OnlyDistributionArtifactRole,
    )
    from onlyalpha.quant_assets.retained_generation import OnlyRetainedRuntimeGenerationProofV1
    from tests.quant_assets.test_retained_generation_proof import _replace_proof_payload, retained_proof_case

    def different_generation():
        proof, graph, bindings = retained_proof_case()
        support = OnlyDistributionArtifactManifest(
            OnlyDistributionArtifactRole.SUPPORT,
            OnlyArtifactSourceProvenanceAuthority.EXTERNAL_RELEASE,
            "upstream",
            "release1",
            "support-extra",
            "1",
            "support_extra-1-py3-none-any.whl",
            "b" * 64,
            3,
        )
        payload = _replace_proof_payload(proof, distributions=(*proof.distributions, support))
        return OnlyRetainedRuntimeGenerationProofV1.from_dict(payload), graph, bindings

    first_root, second_root = tmp_path / "first", tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    publish, store, _, _, _, _ = _publication(first_root)
    first = publish()
    publish_other, _, _, _, _, _ = _publication(second_root, proof_case=different_generation)
    second = publish_other()
    assert first.manifest.result.research_result_fingerprint == second.manifest.result.research_result_fingerprint
    assert first.manifest.artifact_content_fingerprint != second.manifest.artifact_content_fingerprint
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_NOT_FOUND"):
        store.load_exact_for_publication(**_references(second.manifest))
    assert store.load_exact_for_publication(**_references(first.manifest)).manifest == first.manifest


@pytest.mark.parametrize("mutation", ["truncated", "empty", "symlink", "extra_leaf"])
def test_exact_artifact_inspection_rejects_retained_corruption_without_repair(tmp_path, mutation):
    publish, store, _, _, _, _ = _publication(tmp_path)
    artifact = publish()
    root = _root(tmp_path, artifact.manifest.artifact_content_fingerprint)
    manifest = root / "artifact_manifest.json"
    if mutation == "truncated":
        manifest.write_bytes(b"{")
    elif mutation == "empty":
        manifest.unlink()
    elif mutation == "symlink":
        saved = root.parent / "saved-manifest"
        manifest.rename(saved)
        manifest.symlink_to(saved)
    else:
        (root / "unknown").write_bytes(b"extra")
    before = _bytes(tmp_path)
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_CORRUPT"):
        store.load_exact_for_publication(**_references(artifact.manifest))
    assert _bytes(tmp_path) == before


def test_exact_artifact_inspection_rejects_byte_identical_inode_replacement(tmp_path, monkeypatch):
    publish, store, _, _, _, _ = _publication(tmp_path)
    artifact = publish()
    manifest = _root(tmp_path, artifact.manifest.artifact_content_fingerprint) / "artifact_manifest.json"
    verify = store._read_verified

    def substitute(*args, **kwargs):
        loaded = verify(*args, **kwargs)
        saved = manifest.with_name(".original")
        manifest.rename(saved)
        manifest.write_bytes(saved.read_bytes())
        saved.unlink()
        return loaded

    monkeypatch.setattr(store, "_read_verified", substitute)
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_CORRUPT"):
        store.load_exact_for_publication(**_references(artifact.manifest))


def test_exact_artifact_inspection_unavailable_root_is_not_local_not_found(tmp_path):
    publish, store, _, _, _, _ = _publication(tmp_path)
    artifact = publish()
    store._root.rename(tmp_path / "unavailable")
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_CORRUPT"):
        store.load_exact_for_publication(**_references(artifact.manifest))
    assert not store._root.exists()
