"""Receipt-less exact lookup, not scientific absence or execution permission."""

from __future__ import annotations

import errno
import shutil
from copy import copy
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


def _other_generation_publication(tmp_path, first, results, evidence_store):
    from onlyalpha.distribution import (
        OnlyArtifactSourceProvenanceAuthority,
        OnlyDistributionArtifactManifest,
        OnlyDistributionArtifactRole,
    )
    from onlyalpha.quant_assets.retained_generation import OnlyRetainedRuntimeGenerationProofV1
    from onlyalpha.research.artifact import (
        OnlyParquetResearchCalculationArtifactStoreV2,
        OnlyResearchCalculationArtifactMaterializerV2,
    )
    from onlyalpha.research.calculation.backend import OnlyResearchCalculationBackendResolver
    from onlyalpha.research.calculation.execution import OnlyResearchCalculationExecutor
    from onlyalpha.research.calculation.execution_provenance import (
        OnlyResearchRuntimeExecutionProvenanceV1,
        _only_issue_research_runtime_execution_context,
    )
    from tests.quant_assets.test_retained_generation_proof import _replace_proof_payload, retained_proof_case
    from tests.research.calculation.test_execution_readiness_v2 import PUBLICATION, _registry
    from tests.research.calculation.test_result_v2_store import AUDIT
    from tests.support.calculation_publication_input import verified_test_input

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

    proof, graph, bindings = different_generation()
    provenance = OnlyResearchRuntimeExecutionProvenanceV1(
        proof.generation.runtime_generation_fingerprint,
        proof.validation.validation_evidence_fingerprint,
        proof.generation.core_execution.fingerprint,
        proof.generation.catalog_generation_fingerprint,
    )
    other_context = _only_issue_research_runtime_execution_context(provenance, graph.fingerprint, bindings)
    calculations = evidence_store._result_store
    dataset = calculations._dataset_store
    sealed = OnlyResearchCalculationExecutor(
        dataset, OnlyResearchCalculationBackendResolver(_registry())
    )._execute_verified_v2(
        first.manifest.dataset.snapshot_fingerprint, graph, PUBLICATION, runtime_context=other_context
    )
    calculation = calculations.commit(sealed, graph)
    other_evidence = evidence_store._publish_verified(sealed, calculation)
    other_root = tmp_path / "other-artifacts"
    other_root.mkdir()
    second = OnlyResearchCalculationArtifactMaterializerV2(results, dataset, calculations, evidence_store).publish(
        first.manifest.result.research_result_plan_fingerprint,
        ((calculation.manifest.calculation_fingerprint, other_evidence.evidence_fingerprint),),
        runtime_context=other_context,
        retained_generation=proof,
        artifact_store=OnlyParquetResearchCalculationArtifactStoreV2(other_root, audit_time=lambda: AUDIT),
        verified_input=verified_test_input(
            tmp_path,
            first.manifest.result.research_result_plan_fingerprint,
            graph.fingerprint,
            provenance.runtime_generation_fingerprint,
        ),
    )
    return second, calculation, other_evidence, provenance


def test_exact_artifact_inspection_never_selects_shared_result_from_different_generation(tmp_path):
    publish, store, context, selection, results, evidence_store = _publication(tmp_path)
    first = publish()
    second, calculation, other_evidence, provenance = _other_generation_publication(
        tmp_path, first, results, evidence_store
    )
    assert first.manifest.result.research_result_fingerprint == second.manifest.result.research_result_fingerprint
    assert first.manifest.artifact_content_fingerprint != second.manifest.artifact_content_fingerprint
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_NOT_FOUND"):
        store.load_exact_for_publication(**_references(second.manifest))
    # Coexisting complete producers in the same owning namespace remain distinct.
    target = _root(tmp_path, second.manifest.artifact_content_fingerprint)
    target.parent.mkdir(parents=True, exist_ok=True)
    identity = second.manifest.artifact_content_fingerprint
    shutil.copytree(
        tmp_path / "other-artifacts" / "research-calculation-v2" / "sha256" / identity[:2] / identity, target
    )
    assert store.load_exact_for_publication(**_references(second.manifest)).manifest == second.manifest
    assert store.load_exact_for_publication(**_references(first.manifest)).manifest == first.manifest
    assert (
        evidence_store.load_exact_for_result(calculation, other_evidence.research_implementation_bindings, provenance)
        == other_evidence
    )
    assert (
        evidence_store.load_exact_for_result(
            calculation, other_evidence.research_implementation_bindings, context.provenance
        ).evidence_fingerprint
        == selection[0][1]
    )
    crossed = _references(first.manifest)
    crossed["selected_evidence"] = second.manifest.selected_evidence
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_CORRUPT"):
        store.load_exact_for_publication(**crossed)


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


@pytest.mark.parametrize("entry", ["manifest", "partition", "target", "prefix"])
def test_exact_artifact_inspection_rejects_byte_identical_inode_replacement(tmp_path, monkeypatch, entry):
    publish, store, _, _, _, _ = _publication(tmp_path)
    artifact = publish()
    target = _root(tmp_path, artifact.manifest.artifact_content_fingerprint)
    path = {
        "manifest": target / "artifact_manifest.json",
        "partition": target / artifact.manifest.files[0].relative_path,
        "target": target,
        "prefix": target.parent,
    }[entry]
    verify = store._read_verified

    def substitute(*args, **kwargs):
        loaded = verify(*args, **kwargs)
        saved = path.with_name(".original")
        path.rename(saved)
        if saved.is_dir():
            shutil.copytree(saved, path)
            shutil.rmtree(saved)
        else:
            path.write_bytes(saved.read_bytes())
            saved.unlink()
        return loaded

    monkeypatch.setattr(store, "_read_verified", substitute)
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_CORRUPT"):
        store.load_exact_for_publication(**_references(artifact.manifest))


def test_exact_artifact_inspection_unavailable_root_is_not_local_not_found(tmp_path):
    publish, store, _, _, _, _ = _publication(tmp_path)
    artifact = publish()
    store._root.rename(tmp_path / "unavailable")
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_STORE_UNAVAILABLE"):
        store.load_exact_for_publication(**_references(artifact.manifest))
    assert not store._root.exists()


@pytest.mark.parametrize("point", ["lookup", "open", "read", "namespace"])
@pytest.mark.parametrize("error", [errno.EACCES, errno.EIO])
def test_exact_artifact_inspection_io_fault_is_unavailable_not_corrupt_or_missing(tmp_path, monkeypatch, point, error):
    import onlyalpha.research._durability as durability

    publish, store, _, _, _, _ = _publication(tmp_path)
    artifact = publish()
    before = _bytes(tmp_path)
    with monkeypatch.context() as scope:
        if point == "lookup":
            original = Path.lstat

            def fail_lookup(path, *args, **kwargs):
                if path == store._root:
                    raise OSError(error, "injected namespace IO")
                return original(path, *args, **kwargs)

            scope.setattr(Path, "lstat", fail_lookup)
        else:

            def fail(*args, **kwargs):
                raise OSError(error, "injected descriptor IO")

            if point == "open":
                scope.setattr(durability.os, "open", fail)
            elif point == "read":
                scope.setattr(durability._OnlyBoundPublicationTree, "read_bytes", fail)
            else:
                scope.setattr(durability.os, "stat", fail)
        with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_STORE_UNAVAILABLE"):
            store.load_exact_for_publication(**_references(artifact.manifest))
    assert _bytes(tmp_path) == before


def test_exact_artifact_inspection_empty_available_namespace_is_only_local_not_found(tmp_path):
    publish, store, _, _, _, _ = _publication(tmp_path)
    artifact = publish()
    store._root.rename(tmp_path / "saved")
    store._root.mkdir()
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_NOT_FOUND"):
        store.load_exact_for_publication(**_references(artifact.manifest))
    assert not tuple(store._root.iterdir())


def test_exact_artifact_inspection_prefix_symlink_is_corrupt_not_missing(tmp_path):
    publish, store, _, _, _, _ = _publication(tmp_path)
    artifact = publish()
    prefix = _root(tmp_path, artifact.manifest.artifact_content_fingerprint).parent
    saved = prefix.with_name("saved")
    prefix.rename(saved)
    prefix.symlink_to(saved, target_is_directory=True)
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_CORRUPT"):
        store.load_exact_for_publication(**_references(artifact.manifest))


@pytest.mark.parametrize("mutation", ["owner", "nested_relation", "source_ref", "wrong_family"])
def test_exact_artifact_inspection_revalidates_nested_source_proof_before_lookup(tmp_path, monkeypatch, mutation):
    from onlyalpha.canonical import only_canonical_json

    publish, store, _, _, _, _ = _publication(tmp_path)
    artifact = publish()
    source = copy(artifact.manifest.sealed_input)
    payload = source.to_dict()
    if mutation == "owner":
        payload["source_reference"].pop("integration_id")
    elif mutation == "nested_relation":
        payload.pop("integration_binding")
    elif mutation == "source_ref":
        payload["source_reference"]["integration_revision_fingerprint"] = "f" * 64
    else:
        payload["source_reference"]["expected_type_id"] = "other.source"
    object.__setattr__(source, "canonical_json", only_canonical_json(payload))
    kwargs = _references(artifact.manifest)
    kwargs["sealed_input"] = source

    def forbidden(*args, **kwargs):
        raise AssertionError("malformed mandatory proof reached filesystem lookup")

    monkeypatch.setattr(store, "_target", forbidden)
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_CORRUPT"):
        store.load_exact_for_publication(**kwargs)
