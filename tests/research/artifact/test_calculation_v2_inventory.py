"""Current owning inventory, never a cancellation or historical absence witness."""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import shutil
import uuid
from dataclasses import replace
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from onlyalpha.research.artifact.calculation_v2_store import OnlyParquetResearchCalculationArtifactStoreV2
from onlyalpha.research.artifact.errors import OnlyResearchArtifactError
from tests.research.artifact.test_calculation_v2 import _publication, _root
from tests.research.artifact.test_calculation_v2_exact_inspection import _bytes, _other_generation_publication

pytestmark = pytest.mark.contract


def _empty(root):
    root.mkdir()
    (root / ".source-cut.lock").touch()
    return OnlyParquetResearchCalculationArtifactStoreV2(root)


def test_retained_inventory_is_bound_readonly_and_holds_owning_exclusion(tmp_path, monkeypatch):
    from onlyalpha.research.artifact import calculation_v2_store
    from onlyalpha.research.calculation import execution_provenance
    from onlyalpha.research.calculation.execution import OnlyResearchCalculationExecutor
    from onlyalpha.research.dataset import publication_input
    from onlyalpha.research.dataset.parquet_store import OnlyParquetResearchDatasetSnapshotStore

    publish, store, _, _, _, _ = _publication(tmp_path)
    artifact = publish()
    calculation = artifact.manifest.calculations[0].calculation_fingerprint
    before = _bytes(tmp_path)
    actual_open = os.open
    opened = []

    def readonly_open(path, flags, *args, **kwargs):
        assert not flags & (os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_RDWR)
        opened.append(path)
        return actual_open(path, flags, *args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("inventory wrote, acknowledged, executed or read a live predecessor")

    with monkeypatch.context() as scope:
        scope.setattr(os, "open", readonly_open)
        scope.setattr(os, "fsync", forbidden)
        scope.setattr(Path, "mkdir", forbidden)
        scope.setattr(calculation_v2_store, "_read_retained_file", forbidden)
        scope.setattr(calculation_v2_store, "_sync_package", forbidden)
        scope.setattr(OnlyResearchCalculationExecutor, "_execute_verified_v2", forbidden)
        scope.setattr(OnlyParquetResearchDatasetSnapshotStore, "load_verified_table", forbidden)
        scope.setattr(OnlyParquetResearchDatasetSnapshotStore, "acknowledge_exact", forbidden)
        scope.setattr(execution_provenance, "_only_issue_research_runtime_execution_context", forbidden)
        scope.setattr(publication_input, "_only_issue_verified_sealed_chart_publication_input", forbidden)
        with store.inspect_retained_for_calculation(calculation) as retained:
            assert len(retained) == 1
            assert retained[0].manifest == artifact.manifest
            probe = os.open(store._root / ".source-cut.lock", os.O_RDONLY)
            try:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(probe, fcntl.LOCK_SH | fcntl.LOCK_NB)
            finally:
                os.close(probe)
    assert opened
    assert _bytes(tmp_path) == before
    probe = os.open(store._root / ".source-cut.lock", os.O_RDONLY)
    try:
        fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(probe)


@pytest.mark.parametrize("namespace", ["absent", "family", "addressed", "prefix"])
def test_inventory_empty_optional_namespace_is_only_a_current_snapshot(tmp_path, namespace):
    root = tmp_path / "artifacts"
    store = _empty(root)
    path = root / "research-calculation-v2"
    if namespace != "absent":
        path.mkdir()
    if namespace in {"addressed", "prefix"}:
        (path / "sha256").mkdir()
    if namespace == "prefix":
        (path / "sha256" / "ab").mkdir()
    before = _bytes(tmp_path)
    with store.inspect_retained_for_calculation("a" * 64) as retained:
        assert retained == ()
    assert _bytes(tmp_path) == before


@pytest.mark.parametrize("exception_type", [RuntimeError, ValueError, OSError])
def test_inventory_consumer_failure_releases_exclusion_without_publishing(tmp_path, exception_type):
    root = tmp_path / "artifacts"
    store = _empty(root)
    error = exception_type("consumer stopped")
    before = _bytes(tmp_path)
    with pytest.raises(type(error), match="consumer stopped") as raised:
        with store.inspect_retained_for_calculation("a" * 64):
            raise error
    assert raised.value is error
    assert _bytes(tmp_path) == before
    descriptor = os.open(root / ".source-cut.lock", os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(descriptor)


def test_retained_inventory_survives_missing_live_predecessors(tmp_path):
    publish, store, _, _, _, _ = _publication(tmp_path)
    artifact = publish()
    for name in ("owning-input", "calculations", "semantic", "results"):
        (tmp_path / name).rename(tmp_path / f"unavailable-{name}")
    (tmp_path / "source-owner.json").rename(tmp_path / "unavailable-source.json")
    before = _bytes(tmp_path)
    with store.inspect_retained_for_calculation(artifact.manifest.calculations[0].calculation_fingerprint) as retained:
        assert tuple(item.manifest for item in retained) == (artifact.manifest,)
    assert _bytes(tmp_path) == before
    assert all(not (tmp_path / name).exists() for name in ("owning-input", "calculations", "semantic", "results"))


def test_shared_calculation_inventory_retains_all_complete_producers_without_latest_selection(tmp_path):
    publish, store, _, _, results, evidence = _publication(tmp_path)
    first = publish()
    second, _, _, _ = _other_generation_publication(tmp_path, first, results, evidence)
    identity = second.manifest.artifact_content_fingerprint
    target = _root(tmp_path, identity)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        tmp_path / "other-artifacts" / "research-calculation-v2" / "sha256" / identity[:2] / identity, target
    )
    assert first.manifest.result.research_result_fingerprint == second.manifest.result.research_result_fingerprint
    assert first.manifest.expected_runtime_provenance != second.manifest.expected_runtime_provenance
    before = _bytes(tmp_path)
    with store.inspect_retained_for_calculation(first.manifest.calculations[0].calculation_fingerprint) as retained:
        assert {item.manifest.artifact_content_fingerprint for item in retained} == {
            first.manifest.artifact_content_fingerprint,
            second.manifest.artifact_content_fingerprint,
        }
        assert tuple(item.manifest.artifact_content_fingerprint for item in retained) == tuple(
            sorted((first.manifest.artifact_content_fingerprint, second.manifest.artifact_content_fingerprint))
        )
    with store.inspect_retained_for_calculation("f" * 64) as unrelated:
        assert unrelated == ()
    assert _bytes(tmp_path) == before


def test_inventory_calculation_membership_spans_different_portable_result_plans(tmp_path):
    from onlyalpha.canonical import only_canonical_json
    from onlyalpha.research.artifact.calculation_v2_model import (
        OnlyResearchCalculationArtifactFileV2,
        _only_calculation_artifact_reference_manifest,
    )
    from onlyalpha.research.artifact.calculation_v2_sections import _section_json, _section_tables
    from onlyalpha.research.calculation.backend import OnlyResearchCalculationBackendResolver
    from onlyalpha.research.calculation.execution import OnlyResearchCalculationExecutor
    from onlyalpha.research.calculation.execution_provenance import _only_issue_research_runtime_execution_context
    from onlyalpha.research.result.assembler import OnlyResearchResultAssembler
    from onlyalpha.research.result.plan import OnlyResearchResultCalculationPlan, OnlyResearchResultSeriesPlan
    from tests.research.calculation.test_execution_readiness_v2 import PUBLICATION, _graph, _registry
    from tests.research.calculation.test_result_v2_store import AUDIT

    publish, store, _, _, results, evidence = _publication(tmp_path)
    first = publish()
    calculations = evidence._result_store
    datasets = calculations._dataset_store
    graph = _graph(period=1)
    implementation = first.manifest.selected_evidence[0].research_implementation_bindings[0]
    context = _only_issue_research_runtime_execution_context(
        first.manifest.expected_runtime_provenance,
        graph.fingerprint,
        ((graph.nodes[0].fingerprint, implementation.research_implementation_fingerprint),),
    )
    execution = OnlyResearchCalculationExecutor(
        datasets, OnlyResearchCalculationBackendResolver(_registry())
    )._execute_verified_v2(first.manifest.dataset.snapshot_fingerprint, graph, PUBLICATION, runtime_context=context)
    second_calculation = calculations.commit(execution, graph)
    second_evidence = evidence._publish_verified(execution, second_calculation)
    second_id = second_calculation.manifest.calculation_fingerprint
    plan = replace(
        first.manifest.result.plan,
        calculations=tuple(
            sorted(
                (
                    *first.manifest.result.plan.calculations,
                    OnlyResearchResultCalculationPlan(second_id, graph.fingerprint),
                )
            )
        ),
        published_series=tuple(
            sorted(
                (
                    *first.manifest.result.plan.published_series,
                    OnlyResearchResultSeriesPlan(
                        None, second_id, graph.nodes[0].fingerprint, graph.nodes[0].definition.outputs[0].name
                    ),
                )
            )
        ),
    )
    assembled = OnlyResearchResultAssembler(
        None, audit_time=lambda: AUDIT, readiness_result_store=calculations, readiness_evidence_store=evidence
    ).assemble(plan)
    results.commit(assembled)
    dataset = datasets.load_verified_table(first.manifest.dataset.snapshot_fingerprint)
    by_calculation = {
        first.manifest.calculations[0].calculation_fingerprint: calculations.load_verified(
            first.manifest.calculations[0].calculation_fingerprint
        ),
        second_id: second_calculation,
    }
    by_evidence = {
        first.manifest.calculations[0].calculation_fingerprint: first.manifest.selected_evidence[0],
        second_id: second_evidence,
    }
    manifest = _only_calculation_artifact_reference_manifest(
        result=assembled.manifest,
        dataset=dataset.snapshot,
        calculations=tuple(by_calculation[item.calculation_fingerprint].manifest for item in plan.calculations),
        selected_evidence=tuple(by_evidence[item.calculation_fingerprint] for item in plan.calculations),
        retained_generation=first.manifest.retained_generation,
        sealed_input=first.manifest.sealed_input,
    )
    # Copy-only portable fixture: both Calculations/Evidence and this Result came
    # from their canonical producers above. Encoding a replica is not a native
    # materializer invocation, input issuance, Work or Attempt publication proof.
    target = _root(tmp_path, manifest.artifact_content_fingerprint)
    target.mkdir(parents=True)
    for partition in dataset.snapshot.partitions:
        output = target / "dataset" / partition.relative_path
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(datasets._target(dataset.snapshot.snapshot_fingerprint) / partition.relative_path, output)
    for identity, calculation in by_calculation.items():
        for partition in (*calculation.manifest.value_partitions, *calculation.manifest.readiness_partitions):
            output = target / "calculations" / identity / partition.relative_path
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(calculations._target(identity) / partition.relative_path, output)
    for relative, table in _section_tables(manifest, dataset.table, by_calculation).items():
        pq.write_table(table, target / relative)
    for relative, raw in _section_json(manifest).items():
        (target / relative).write_bytes(raw)
    descriptors = []
    for relative in sorted(manifest.expected_files):
        raw = (target / relative).read_bytes()
        descriptors.append(OnlyResearchCalculationArtifactFileV2(relative, hashlib.sha256(raw).hexdigest(), len(raw)))
    manifest = replace(manifest, files=tuple(descriptors), created_at=AUDIT)
    (target / "artifact_manifest.json").write_text(only_canonical_json(manifest.to_dict()))
    assert manifest.result.research_result_plan_fingerprint != first.manifest.result.research_result_plan_fingerprint
    before = _bytes(tmp_path)
    with store.inspect_retained_for_calculation(first.manifest.calculations[0].calculation_fingerprint) as retained:
        assert {item.manifest.artifact_content_fingerprint for item in retained} == {
            first.manifest.artifact_content_fingerprint,
            manifest.artifact_content_fingerprint,
        }
    with store.inspect_retained_for_calculation(second_id) as retained:
        assert tuple(item.manifest for item in retained) == (manifest,)
    assert _bytes(tmp_path) == before


@pytest.mark.parametrize("missing", ["root", "lock"])
def test_inventory_missing_anchor_is_unavailable_without_creation(tmp_path, missing):
    root = tmp_path / "artifacts"
    if missing == "lock":
        root.mkdir()
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_STORE_UNAVAILABLE"):
        with OnlyParquetResearchCalculationArtifactStoreV2(root).inspect_retained_for_calculation("a" * 64):
            pytest.fail("missing owning anchor became an empty inventory")
    assert root.exists() == (missing == "lock")
    assert not (root / ".source-cut.lock").exists()


@pytest.mark.parametrize("identity", [None, True, "", "A" * 64, "a" * 63])
def test_inventory_rejects_noncanonical_selector_without_provisioning(tmp_path, identity):
    root = tmp_path / "artifacts"
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_IDENTITY_MISMATCH"):
        with OnlyParquetResearchCalculationArtifactStoreV2(root).inspect_retained_for_calculation(identity):
            pytest.fail("invalid selector became an empty inventory")
    assert not root.exists()


@pytest.mark.parametrize("fault", [errno.EACCES, errno.EIO])
def test_inventory_io_failure_is_not_an_empty_snapshot(tmp_path, monkeypatch, fault):
    store = _empty(tmp_path / "artifacts")
    actual_open = os.open

    def unavailable(path, *args, **kwargs):
        if str(path) == ".source-cut.lock":
            raise OSError(fault, "controlled owning read failure")
        return actual_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", unavailable)
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_STORE_UNAVAILABLE"):
        with store.inspect_retained_for_calculation("a" * 64):
            pytest.fail("I/O failure became an empty inventory")


@pytest.mark.parametrize(
    "mutation", ["unknown_family_entry", "bad_prefix", "wrong_address", "bad_stage", "stage_symlink"]
)
def test_noncanonical_namespace_and_stage_cannot_hide_publication(tmp_path, mutation):
    publish, store, _, _, _, _ = _publication(tmp_path)
    artifact = publish()
    target = _root(tmp_path, artifact.manifest.artifact_content_fingerprint)
    if mutation == "unknown_family_entry":
        (target.parents[2] / "unknown").mkdir()
    elif mutation == "bad_prefix":
        (target.parents[1] / "zz").mkdir()
    elif mutation == "wrong_address":
        target.rename(target.parent / ("f" * 64))
    elif mutation == "bad_stage":
        (target.parent / ".stage-unclassified").mkdir()
    else:
        (target.parent / f".stage-{uuid.uuid4().hex}").symlink_to(target, target_is_directory=True)
    before = _bytes(tmp_path)
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_CORRUPT"):
        with store.inspect_retained_for_calculation("a" * 64):
            pytest.fail("unclassified namespace authorized non-match")
    assert _bytes(tmp_path) == before


def test_inventory_ignores_only_canonical_unpublished_crash_staging_and_old_profiles(tmp_path):
    publish, store, _, _, _, _ = _publication(tmp_path)
    artifact = publish()
    target = _root(tmp_path, artifact.manifest.artifact_content_fingerprint)
    stage = target.parent / f".stage-{uuid.uuid4().hex}"
    stage.mkdir()
    (stage / "interrupted").write_bytes(b"partial bytes, not a publication")
    legacy = store._root / "research-scientific"
    legacy.mkdir()
    (legacy / "unreadable-by-v2").write_bytes(b"not a V2 package")
    before = _bytes(tmp_path)
    with store.inspect_retained_for_calculation(artifact.manifest.calculations[0].calculation_fingerprint) as retained:
        assert tuple(item.manifest for item in retained) == (artifact.manifest,)
    assert _bytes(tmp_path) == before


@pytest.mark.parametrize("mutation", ["manifest", "partition", "package", "prefix", "owner", "membership"])
def test_inventory_rechecks_every_binding_before_successful_exit(tmp_path, mutation):
    publish, store, _, _, _, _ = _publication(tmp_path)
    artifact = publish()
    target = _root(tmp_path, artifact.manifest.artifact_content_fingerprint)
    path = {
        "manifest": target / "artifact_manifest.json",
        "partition": target / artifact.manifest.files[0].relative_path,
        "package": target,
        "prefix": target.parent,
        "owner": store._root,
        "membership": target.parent,
    }[mutation]
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_CORRUPT"):
        with store.inspect_retained_for_calculation(
            artifact.manifest.calculations[0].calculation_fingerprint
        ) as retained:
            assert len(retained) == 1
            if mutation == "membership":
                (path / f".stage-{uuid.uuid4().hex}").mkdir()
            else:
                original = tmp_path / "original-binding"
                path.rename(original)
                if original.is_dir():
                    shutil.copytree(original, path)
                else:
                    path.write_bytes(original.read_bytes())


@pytest.mark.parametrize("selected", [True, False])
@pytest.mark.parametrize("mutation", ["generation", "result_owner", "nested_result", "source", "duplicate", "family"])
def test_incomplete_provenance_cannot_be_filtered_as_an_unrelated_calculation(tmp_path, selected, mutation):
    publish, store, _, _, _, _ = _publication(tmp_path)
    artifact = publish()
    target = _root(tmp_path, artifact.manifest.artifact_content_fingerprint)
    manifest = target / "artifact_manifest.json"
    payload = json.loads(manifest.read_text())
    if mutation == "generation":
        payload["retained_generation"] = {}
    elif mutation == "result_owner":
        payload["result"]["research_result_fingerprint"] = "f" * 64
    elif mutation == "nested_result":
        payload["selected_evidence"][0]["calculation_result_fingerprint"] = "f" * 64
    elif mutation == "source":
        payload["sealed_input"] = {}
    elif mutation == "duplicate":
        payload["selected_evidence"] *= 2
    else:
        payload["profile"] = "RESEARCH_SCIENTIFIC_V1"
    manifest.write_text(json.dumps(payload))
    calculation = artifact.manifest.calculations[0].calculation_fingerprint if selected else "f" * 64
    before = _bytes(tmp_path)
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_CORRUPT"):
        with store.inspect_retained_for_calculation(calculation):
            pytest.fail("incomplete producer proof became non-match")
    assert _bytes(tmp_path) == before
