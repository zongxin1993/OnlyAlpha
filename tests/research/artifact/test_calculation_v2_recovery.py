"""Deterministic process death and every Artifact publication durability boundary."""

from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from threading import Barrier, local

import pytest

from onlyalpha.research.artifact import (
    OnlyParquetResearchCalculationArtifactStoreV2,
    OnlyResearchCalculationArtifactMaterializerV2,
)
from onlyalpha.research.artifact.calculation_v2_model import OnlyResearchCalculationArtifactManifestV2
from onlyalpha.research.artifact.errors import OnlyResearchArtifactError
from onlyalpha.research.calculation.execution import OnlyResearchCalculationImplementationBinding
from onlyalpha.research.calculation.execution_evidence_v2 import OnlyResearchCalculationExecutionEvidenceStoreV2
from onlyalpha.research.calculation.execution_provenance import (
    OnlyResearchRuntimeExecutionProvenanceV1,
    _only_issue_research_runtime_execution_context,
)
from onlyalpha.research.calculation.result_v2_store import OnlyParquetResearchCalculationResultStoreV2
from onlyalpha.research.dataset import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.result import OnlyJsonResearchResultStore
from tests.quant_assets.test_retained_generation_proof import retained_proof_case
from tests.research.artifact.test_calculation_v2 import _publication, _root
from tests.research.calculation.test_result_v2_store import AUDIT
from tests.support.calculation_publication_input import verified_test_input

pytestmark = pytest.mark.contract


def _reenter(root):
    proof, graph, bindings = retained_proof_case()
    context = _only_issue_research_runtime_execution_context(
        OnlyResearchRuntimeExecutionProvenanceV1(
            proof.generation.runtime_generation_fingerprint,
            proof.validation.validation_evidence_fingerprint,
            proof.generation.core_execution.fingerprint,
            proof.generation.catalog_generation_fingerprint,
        ),
        graph.fingerprint,
        bindings,
    )
    datasets = OnlyParquetResearchDatasetSnapshotStore(root / "owning-input" / "dataset")
    calculations = OnlyParquetResearchCalculationResultStoreV2(
        root / "calculations", datasets, audit_time=lambda: AUDIT
    )
    evidence = OnlyResearchCalculationExecutionEvidenceStoreV2(root / "semantic", calculations)
    results = OnlyJsonResearchResultStore(
        root / "results", None, readiness_result_store=calculations, readiness_evidence_store=evidence
    )
    (result_file,) = (root / "results").rglob("manifest.json")
    plan = json.loads(result_file.read_text())["research_result_plan_fingerprint"]
    calculation = next(iter(results.load_verified(plan).manifest.calculation_results))
    selected = evidence.require_exact_for_result(
        calculations.load_verified(calculation.calculation_fingerprint),
        tuple(OnlyResearchCalculationImplementationBinding(*item) for item in bindings),
        context.provenance,
    )
    return OnlyResearchCalculationArtifactMaterializerV2(results, datasets, calculations, evidence).publish(
        plan,
        ((selected.calculation_fingerprint, selected.evidence_fingerprint),),
        runtime_context=context,
        retained_generation=proof,
        verified_input=verified_test_input(
            root, plan, graph.fingerprint, context.provenance.runtime_generation_fingerprint
        ),
        artifact_store=OnlyParquetResearchCalculationArtifactStoreV2(root / "artifacts", audit_time=lambda: AUDIT),
    )


@pytest.mark.parametrize("after_rename", (False, True))
def test_process_death_preserves_valid_prefix_and_fresh_process_reentry(tmp_path, after_rename):
    child = r"""
import os, sys
from pathlib import Path
from tests.research.artifact.test_calculation_v2 import _publication
from onlyalpha.research.artifact import calculation_v2_store
publish, _, _, _, _, _ = _publication(Path(sys.argv[1]))
rename = calculation_v2_store._rename_exclusive
def die(source, target):
    if sys.argv[2] == 'after':
        rename(source, target)
    os._exit(91)
calculation_v2_store._rename_exclusive = die
publish()
"""
    process = subprocess.run(
        [sys.executable, "-c", child, str(tmp_path), "after" if after_rename else "before"],
        capture_output=True,
        text=True,
    )
    assert process.returncode == 91, process.stderr
    assert tuple((tmp_path / "results").rglob("manifest.json"))
    assert (
        bool(
            tuple(
                path
                for path in (tmp_path / "artifacts").rglob("artifact_manifest.json")
                if not path.parent.name.startswith(".stage-")
            )
        )
        == after_rename
    )
    families = ("owning-input/dataset", "calculations", "semantic", "results")
    before = {
        family: {path: path.read_bytes() for path in (tmp_path / family).rglob("*") if path.is_file()}
        for family in families
    }
    assert all(before.values()), "every monitored predecessor must have retained files"
    source_path = tmp_path / "source-owner.json"
    source_before = source_path.read_bytes()
    assert source_before
    recover = r"""
import sys
from pathlib import Path
from tests.research.artifact.test_calculation_v2_recovery import _reenter
from onlyalpha.research.calculation.execution import OnlyResearchCalculationExecutor
def fail(*args, **kwargs):
    raise AssertionError('fresh Artifact recovery reexecuted calculation')
OnlyResearchCalculationExecutor._execute_verified_v2 = fail
artifact = _reenter(Path(sys.argv[1]))
print(artifact.manifest.artifact_content_fingerprint)
"""
    identity = subprocess.check_output([sys.executable, "-c", recover, str(tmp_path)], text=True).strip()
    (result_file,) = (tmp_path / "results").rglob("manifest.json")
    result_id = json.loads(result_file.read_text())["research_result_fingerprint"]
    assert OnlyParquetResearchCalculationArtifactStoreV2(tmp_path / "artifacts").load_verified(
        identity, research_result_fingerprint=result_id
    )
    assert before == {
        family: {path: path.read_bytes() for path in (tmp_path / family).rglob("*") if path.is_file()}
        for family in families
    }
    assert source_path.read_bytes() == source_before


@pytest.mark.parametrize(
    "site", ("file", "staged_dir", "target_dir", "prefix", "sha256", "profile", "anchor", "rename")
)
@pytest.mark.parametrize("existing", (False, True))
def test_each_required_fsync_or_rename_failure_never_reports_publication_success(tmp_path, monkeypatch, site, existing):
    from onlyalpha.research.artifact import calculation_v2_store

    publish, store, _, _, _, _ = _publication(tmp_path)
    original = publish() if existing else None
    sync = calculation_v2_store._sync_directory
    sync_package = calculation_v2_store._sync_package
    triggered = []

    def unavailable_sync(path, **kwargs):
        selected = (
            site == "staged_dir"
            and path.name.startswith(".stage-")
            or site == "target_dir"
            and len(path.name) == 64
            or site == "prefix"
            and len(path.name) == 2
            or site == "sha256"
            and path.name == "sha256"
            or site == "profile"
            and path.name == "research-calculation-v2"
            or site == "anchor"
            and path == tmp_path / "artifacts"
        )
        if selected:
            triggered.append(path)
            raise OSError("controlled required directory sync failure")
        sync(path, **kwargs)

    def unavailable_package(root, **kwargs):
        def unavailable_fsync(_):
            triggered.append(root)
            raise OSError("controlled retained file sync failure")

        with monkeypatch.context() as scope:
            scope.setattr(calculation_v2_store.os, "fsync", unavailable_fsync)
            sync_package(root, **kwargs)

    def unavailable_rename(*args):
        triggered.append(args)
        raise OSError("controlled exclusive rename failure")

    monkeypatch.setattr(calculation_v2_store, "_sync_directory", unavailable_sync)
    if site == "file":
        monkeypatch.setattr(calculation_v2_store, "_sync_package", unavailable_package)
    if site == "rename":
        monkeypatch.setattr(calculation_v2_store, "_rename_exclusive", unavailable_rename)
    # Reuse performs no staging/rename; those obligations are genuinely N/A.
    if existing and site in {"staged_dir", "rename"}:
        assert publish().manifest == original.manifest
        assert not triggered
        return
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_COMMIT_FAILED"):
        publish()
    assert triggered
    monkeypatch.undo()
    recovered = publish()
    assert (
        store.load_verified(
            recovered.manifest.artifact_content_fingerprint,
            research_result_fingerprint=recovered.manifest.result.research_result_fingerprint,
        ).manifest
        == recovered.manifest
    )
    if original is not None:
        assert original.manifest == recovered.manifest


@pytest.mark.parametrize("predecessor", ("dataset", "calculation", "result", "evidence"))
def test_live_predecessor_loss_does_not_restore_from_portable_publication(tmp_path, predecessor):
    publish, store, _, _, _, _ = _publication(tmp_path)
    artifact = publish()
    identity = artifact.manifest.artifact_content_fingerprint
    family = {
        "dataset": "owning-input/dataset",
        "calculation": "calculations",
        "result": "results",
        "evidence": "semantic",
    }[predecessor]
    (tmp_path / family).rename(tmp_path / f"unavailable-{predecessor}")
    before = {path: path.read_bytes() for path in _root(tmp_path, identity).rglob("*") if path.is_file()}
    with pytest.raises(OnlyResearchArtifactError):
        publish()
    assert not (tmp_path / family).exists()
    assert (
        store.load_verified(
            identity, research_result_fingerprint=artifact.manifest.result.research_result_fingerprint
        ).manifest
        == artifact.manifest
    )
    assert before == {path: path.read_bytes() for path in _root(tmp_path, identity).rglob("*") if path.is_file()}


@pytest.mark.parametrize("existing", (False, True))
def test_dataset_fsync_failure_blocks_artifact_publication_and_reuse(tmp_path, monkeypatch, existing):
    from onlyalpha.research.dataset import parquet_store

    publish, store, _, _, _, _ = _publication(tmp_path)
    original = publish() if existing else None
    sync = parquet_store.os.fsync
    touched = []

    def unavailable(descriptor):
        import os

        path = tmp_path / "owning-input" / "dataset"
        actual, expected = os.fstat(descriptor), path.stat()
        if (actual.st_dev, actual.st_ino) == (expected.st_dev, expected.st_ino):
            touched.append(path)
            raise OSError("controlled Dataset acknowledgement failure")
        sync(descriptor)

    monkeypatch.setattr(parquet_store.os, "fsync", unavailable)
    with pytest.raises(OnlyResearchArtifactError):
        publish()
    assert touched
    if original is None:
        assert not tuple((tmp_path / "artifacts").iterdir())
    else:
        assert (
            store.load_verified(
                original.manifest.artifact_content_fingerprint,
                research_result_fingerprint=original.manifest.result.research_result_fingerprint,
            ).manifest
            == original.manifest
        )
    monkeypatch.undo()
    assert publish()


def test_equal_race_loser_must_acknowledge_independently_of_durable_winner(tmp_path, monkeypatch):
    from onlyalpha.research.artifact import calculation_v2_store

    publish, store, _, _, _, _ = _publication(tmp_path)
    barrier = Barrier(2)
    role = local()
    rename = calculation_v2_store._rename_exclusive
    sync_package = calculation_v2_store._sync_package

    def raced(source, target):
        barrier.wait(timeout=20)
        try:
            return rename(source, target)
        except FileExistsError:
            role.loser = True
            raise

    def fail_loser_ack(root, **kwargs):
        if getattr(role, "loser", False):
            raise OSError("controlled equal-race loser acknowledgement failure")
        sync_package(root, **kwargs)

    monkeypatch.setattr(calculation_v2_store, "_rename_exclusive", raced)
    monkeypatch.setattr(calculation_v2_store, "_sync_package", fail_loser_ack)
    with ThreadPoolExecutor(2) as pool:
        futures = (pool.submit(publish), pool.submit(publish))
        successes, failures = [], []
        for future in futures:
            try:
                successes.append(future.result())
            except OnlyResearchArtifactError as exc:
                failures.append(exc)
    assert len(successes) == len(failures) == 1
    assert "ARTIFACT_COMMIT_FAILED" in str(failures[0])
    assert (
        store.load_verified(
            successes[0].manifest.artifact_content_fingerprint,
            research_result_fingerprint=successes[0].manifest.result.research_result_fingerprint,
        ).manifest
        == successes[0].manifest
    )
    monkeypatch.undo()
    assert publish().manifest == successes[0].manifest


def test_encoding_location_and_audit_time_are_not_artifact_logical_identity(tmp_path):
    publish, _, _, _, _, _ = _publication(tmp_path)
    first = publish()
    other = tmp_path / "different-physical-encoding"
    other.mkdir()
    second = publish(
        store=OnlyParquetResearchCalculationArtifactStoreV2(
            other,
            compression="snappy",
            row_group_size=1,
            audit_time=lambda: AUDIT + timedelta(days=1),
        )
    )
    assert first.manifest.artifact_content_fingerprint == second.manifest.artifact_content_fingerprint
    assert first.manifest.created_at != second.manifest.created_at
    assert first.manifest.files != second.manifest.files
    assert first.dataset_table.equals(second.dataset_table)
    assert first.manifest.result == second.manifest.result


@pytest.mark.parametrize(
    "dimension",
    (
        "whole_context",
        "owner",
        "nested_relation",
        "source_ref",
        "leaf_identity",
        "duplicate_owner",
        "wrong_family",
        "complete_different_generation",
        "missing_evidence",
        "duplicate_evidence",
    ),
)
def test_portable_structural_proof_mutations_reject_before_outer_identity_check(tmp_path, dimension):
    publish, _, _, _, _, _ = _publication(tmp_path)
    payload = deepcopy(publish().manifest.to_dict())
    proof = payload["retained_generation"]
    if dimension == "whole_context":
        payload.pop("retained_generation")
    elif dimension == "owner":
        proof["generation"].pop("core_execution")
    elif dimension == "nested_relation":
        proof["validation"].pop("catalog_generation_fingerprint")
    elif dimension == "source_ref":
        proof["catalog"]["providers"][0]["manifest"].pop("source")
    elif dimension == "leaf_identity":
        proof["implementation_manifests"][0]["implementation_fingerprint"] = "invalid"
    elif dimension == "duplicate_owner":
        proof["distributions"].append(proof["distributions"][0])
    elif dimension == "wrong_family":
        payload["calculations"][0]["schema_version"] = 1
    elif dimension == "complete_different_generation":
        # Complete provenance remains structurally valid and self-hashed, but has
        # no equality relation to the actual retained generation owner.
        from dataclasses import replace

        from onlyalpha.research.calculation.execution_evidence_v2 import OnlyResearchCalculationExecutionEvidenceV2

        original = OnlyResearchCalculationExecutionEvidenceV2.from_dict(payload["selected_evidence"][0])
        different = replace(
            original,
            runtime_execution_provenance=replace(
                original.runtime_execution_provenance, runtime_generation_fingerprint="f" * 64
            ),
        )
        payload["selected_evidence"] = [different.to_dict()]
    elif dimension == "missing_evidence":
        payload["selected_evidence"] = []
    else:
        payload["selected_evidence"] *= 2
    with pytest.raises((ValueError, KeyError, TypeError)) as raised:
        OnlyResearchCalculationArtifactManifestV2.from_dict(payload)
    assert "Artifact logical identity differs" not in str(raised.value)
