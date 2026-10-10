"""Related retained publications protect the complete live immutable prefix."""

from __future__ import annotations

import errno
import fcntl
import os
import shutil
from contextlib import contextmanager

import pytest

from onlyalpha.research.artifact.errors import OnlyResearchArtifactError
from onlyalpha.research.artifact.publication_inspection import _only_inspect_calculation_publication_prefix
from onlyalpha.research.calculation.errors import OnlyResearchCalculationError
from onlyalpha.research.dataset.parquet_store import (
    OnlyParquetResearchDatasetSnapshotStore,
    OnlyResearchDatasetStoreError,
)
from onlyalpha.research.result.errors import OnlyResearchResultStoreError
from onlyalpha.research.result.result_store import OnlyJsonResearchResultStore
from tests.research.artifact.test_calculation_v2 import _publication, _root
from tests.research.artifact.test_calculation_v2_exact_inspection import _bytes, _other_generation_publication
from tests.research.artifact.test_calculation_v2_inventory import _other_plan_portable_copy

pytestmark = pytest.mark.contract


def _inspection(store, artifact, results, evidence):
    return _only_inspect_calculation_publication_prefix(
        artifacts=store,
        results=results,
        evidence=evidence,
        calculations=evidence._result_store,
        calculation_fingerprint=artifact.manifest.calculations[0].calculation_fingerprint,
        result_plan=artifact.manifest.result.plan,
        implementation_bindings=artifact.manifest.selected_evidence[0].research_implementation_bindings,
        runtime_provenance=artifact.manifest.expected_runtime_provenance,
    )


def _case(tmp_path):
    publish, store, _, _, results, evidence = _publication(tmp_path)
    artifact = publish()
    return store, artifact, results, evidence


def test_prefix_inspection_is_zero_write_and_keeps_every_owner_excluded(tmp_path, monkeypatch):
    store, artifact, results, evidence = _case(tmp_path)
    roots = (store._root, results._root, evidence._semantic_root, evidence._result_store._root)
    before = _bytes(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("publication inspection wrote or acknowledged")

    monkeypatch.setattr(os, "fsync", forbidden)
    monkeypatch.setattr(OnlyParquetResearchDatasetSnapshotStore, "acknowledge_exact", forbidden)
    with _inspection(store, artifact, results, evidence) as (calculation, producer, result):
        assert (
            calculation.manifest.calculation_result_fingerprint
            == artifact.manifest.calculations[0].calculation_result_fingerprint
        )
        assert producer == artifact.manifest.selected_evidence[0]
        assert result.manifest.research_result_fingerprint == artifact.manifest.result.research_result_fingerprint
        for root in roots:
            descriptor = os.open(root / ".source-cut.lock", os.O_RDONLY)
            try:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
            finally:
                os.close(descriptor)
    assert _bytes(tmp_path) == before
    for root in roots:
        descriptor = os.open(root / ".source-cut.lock", os.O_RDONLY)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)


@pytest.mark.parametrize("missing", ["result", "evidence", "calculation", "dataset", "all_live"])
def test_retained_artifact_missing_any_live_predecessor_cannot_be_fresh_work(tmp_path, missing):
    store, artifact, results, evidence = _case(tmp_path)
    calculation = artifact.manifest.calculations[0]
    paths = {
        "result": results._target(artifact.manifest.result.research_result_plan_fingerprint),
        "evidence": evidence._target(artifact.manifest.selected_evidence[0].evidence_fingerprint),
        "calculation": evidence._result_store._target(calculation.calculation_fingerprint),
        "dataset": evidence._result_store._dataset_store._target(calculation.dataset_snapshot_fingerprint),
    }
    removed = tuple(paths) if missing == "all_live" else (missing,)
    for name in removed:
        paths[name].rename(tmp_path / f"unavailable-{name}")
    before = _bytes(tmp_path)
    with pytest.raises(
        (OnlyResearchCalculationError, OnlyResearchResultStoreError, OnlyResearchDatasetStoreError)
    ) as raised:
        with _inspection(store, artifact, results, evidence):
            pytest.fail("retained downstream authorized missing-prefix reconstruction")
    expected = {
        "result": "RESEARCH_RESULT_NOT_FOUND",
        "all_live": "RESEARCH_RESULT_NOT_FOUND",
        "calculation": "RESULT_NOT_FOUND",
        "evidence": "RESEARCH_RESULT_CORRUPT",
        "dataset": "DATASET_SNAPSHOT_NOT_FOUND",
    }
    assert expected[missing] in str(raised.value)
    assert _bytes(tmp_path) == before
    assert all(not paths[name].exists() for name in removed)


@pytest.mark.parametrize(
    "mutation", ["result_manifest", "calculation_manifest", "evidence_manifest", "dataset_partition", "owner"]
)
def test_prefix_retains_bindings_until_common_relation_exit(tmp_path, mutation):
    store, artifact, results, evidence = _case(tmp_path)
    calculation = artifact.manifest.calculations[0]
    paths = {
        "result_manifest": results._target(artifact.manifest.result.research_result_plan_fingerprint) / "manifest.json",
        "calculation_manifest": evidence._result_store._target(calculation.calculation_fingerprint) / "manifest.json",
        "evidence_manifest": evidence._target(artifact.manifest.selected_evidence[0].evidence_fingerprint)
        / "manifest.json",
        "dataset_partition": evidence._result_store._dataset_store._target(calculation.dataset_snapshot_fingerprint)
        / artifact.manifest.dataset.partitions[0].relative_path,
        "owner": evidence._result_store._root,
    }
    path = paths[mutation]
    with pytest.raises(
        (OnlyResearchCalculationError, OnlyResearchResultStoreError, OnlyResearchDatasetStoreError)
    ) as raised:
        with _inspection(store, artifact, results, evidence):
            original = tmp_path / "original-binding"
            path.rename(original)
            if original.is_dir():
                shutil.copytree(original, path)
            else:
                path.write_bytes(original.read_bytes())
    assert "CORRUPT" in str(raised.value)


@pytest.mark.parametrize("mutation", ["result", "calculation", "evidence", "dataset", "artifact_partition"])
def test_prefix_rechecks_in_place_content_not_only_leaf_inode(tmp_path, mutation):
    store, artifact, results, evidence = _case(tmp_path)
    calculation = artifact.manifest.calculations[0]
    path = {
        "result": results._target(artifact.manifest.result.research_result_plan_fingerprint) / "manifest.json",
        "calculation": evidence._result_store._target(calculation.calculation_fingerprint) / "manifest.json",
        "evidence": evidence._target(artifact.manifest.selected_evidence[0].evidence_fingerprint) / "manifest.json",
        "dataset": evidence._result_store._dataset_store._target(calculation.dataset_snapshot_fingerprint)
        / "manifest.json",
        "artifact_partition": _root(tmp_path, artifact.manifest.artifact_content_fingerprint)
        / "dataset"
        / artifact.manifest.dataset.partitions[0].relative_path,
    }[mutation]
    inode = path.stat().st_ino
    with pytest.raises(
        (
            OnlyResearchCalculationError,
            OnlyResearchResultStoreError,
            OnlyResearchDatasetStoreError,
            OnlyResearchArtifactError,
        )
    ) as raised:
        with _inspection(store, artifact, results, evidence):
            path.write_bytes(path.read_bytes() + b" ")
            assert path.stat().st_ino == inode
    assert "CORRUPT" in str(raised.value)


@pytest.mark.parametrize("root_index", range(4))
@pytest.mark.parametrize("missing", ["root", "lock"])
def test_prefix_missing_preprovisioned_owner_is_unavailable_not_zero(tmp_path, root_index, missing):
    store, artifact, results, evidence = _case(tmp_path)
    roots = (store._root, results._root, evidence._semantic_root, evidence._result_store._root)
    path = roots[root_index] if missing == "root" else roots[root_index] / ".source-cut.lock"
    path.rename(tmp_path / "unavailable-owner")
    before = _bytes(tmp_path)
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_PUBLICATION_STORE_UNAVAILABLE"):
        with _inspection(store, artifact, results, evidence):
            pytest.fail("missing owner became ZERO")
    assert not path.exists()
    assert _bytes(tmp_path) == before


@pytest.mark.parametrize("fault", [errno.EACCES, errno.EIO])
def test_prefix_lock_io_is_unavailable_not_corrupt_or_empty(tmp_path, monkeypatch, fault):
    store, artifact, results, evidence = _case(tmp_path)
    actual_open = os.open

    def unavailable(path, *args, **kwargs):
        if str(path) == ".source-cut.lock":
            raise OSError(fault, "controlled owner failure")
        return actual_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", unavailable)
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_PUBLICATION_STORE_UNAVAILABLE"):
        with _inspection(store, artifact, results, evidence):
            pytest.fail("I/O failure became ZERO")


def test_other_generation_retained_artifact_still_protects_its_selected_producer(tmp_path):
    store, first, results, evidence = _case(tmp_path)
    second, _, second_evidence, _ = _other_generation_publication(tmp_path, first, results, evidence)
    identity = second.manifest.artifact_content_fingerprint
    target = _root(tmp_path, identity)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        tmp_path / "other-artifacts" / "research-calculation-v2" / "sha256" / identity[:2] / identity, target
    )
    with _inspection(store, first, results, evidence) as (_, producer, _):
        assert producer == first.manifest.selected_evidence[0]
    evidence._target(second_evidence.evidence_fingerprint).rename(tmp_path / "lost-other-producer")
    before = _bytes(tmp_path)
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_EVIDENCE_NOT_FOUND"):
        with _inspection(store, first, results, evidence):
            pytest.fail("different G was incorrectly irrelevant to retained closure")
    assert _bytes(tmp_path) == before


@pytest.mark.parametrize("missing", ["result", "calculation", "evidence"])
def test_related_other_plan_requires_its_entire_membership_not_only_shared_calculation(tmp_path, missing):
    store, first, results, evidence = _case(tmp_path)
    manifest = _other_plan_portable_copy(tmp_path, store, first, results, evidence)
    second = next(
        item
        for item in manifest.calculations
        if item.calculation_fingerprint != first.manifest.calculations[0].calculation_fingerprint
    )
    producer = next(
        item for item in manifest.selected_evidence if item.calculation_fingerprint == second.calculation_fingerprint
    )
    with _inspection(store, first, results, evidence) as (_, selected, _):
        assert selected == first.manifest.selected_evidence[0]
    target = {
        "result": results._target(manifest.result.research_result_plan_fingerprint),
        "calculation": evidence._result_store._target(second.calculation_fingerprint),
        "evidence": evidence._target(producer.evidence_fingerprint),
    }[missing]
    target.rename(tmp_path / "unavailable-other-plan-member")
    before = _bytes(tmp_path)
    with pytest.raises((OnlyResearchCalculationError, OnlyResearchResultStoreError)) as raised:
        with _inspection(store, first, results, evidence):
            pytest.fail("a shared Calculation hid incomplete other-Plan membership")
    assert {
        "result": "RESEARCH_RESULT_NOT_FOUND",
        "calculation": "RESULT_NOT_FOUND",
        "evidence": "RESEARCH_RESULT_CORRUPT",
    }[missing] in str(raised.value)
    assert _bytes(tmp_path) == before
    assert not target.exists()


@pytest.mark.parametrize("state", ["zero", "calculation", "evidence", "result"])
def test_available_partial_prefix_is_not_confused_with_retained_downstream_loss(tmp_path, state):
    store, artifact, results, evidence = _case(tmp_path)
    paths = [
        _root(tmp_path, artifact.manifest.artifact_content_fingerprint),
        results._target(artifact.manifest.result.research_result_plan_fingerprint),
        evidence._target(artifact.manifest.selected_evidence[0].evidence_fingerprint),
        evidence._result_store._target(artifact.manifest.calculations[0].calculation_fingerprint),
    ]
    removed = {"result": 1, "evidence": 2, "calculation": 3, "zero": 4}[state]
    for index, path in enumerate(paths[:removed]):
        path.rename(tmp_path / f"unavailable-{index}")
    before = _bytes(tmp_path)
    with _inspection(store, artifact, results, evidence) as (calculation, producer, result):
        assert (calculation is None) == (state == "zero")
        assert (producer is None) == (state in {"zero", "calculation"})
        assert (result is None) == (state != "result")
    assert _bytes(tmp_path) == before


@pytest.mark.parametrize("alias", ["adjacent", "cycle"])
def test_lock_alias_uses_actual_inode_and_refuses_order_cycles_before_locking(tmp_path, monkeypatch, alias):
    store, artifact, results, evidence = _case(tmp_path)
    roots = (store._root, results._root, evidence._semantic_root, evidence._result_store._root)
    left, right = (1, 2) if alias == "adjacent" else (0, 3)
    (roots[right] / ".source-cut.lock").unlink()
    os.link(roots[left] / ".source-cut.lock", roots[right] / ".source-cut.lock")
    actual_flock = fcntl.flock
    exclusive = []

    def tracked(descriptor, mode):
        if mode == fcntl.LOCK_EX:
            identity = os.fstat(descriptor)
            exclusive.append((identity.st_dev, identity.st_ino))
        return actual_flock(descriptor, mode)

    monkeypatch.setattr(fcntl, "flock", tracked)
    if alias == "cycle":
        with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_PUBLICATION_CORRUPT"):
            with _inspection(store, artifact, results, evidence):
                pytest.fail("lock-order cycle was admitted")
        assert exclusive == []
    else:
        with _inspection(store, artifact, results, evidence):
            assert len(exclusive) == len(set(exclusive)) == 3


@pytest.mark.parametrize("exception_type", [RuntimeError, ValueError, OSError])
def test_prefix_consumer_exception_is_not_reclassified_and_all_locks_are_released(tmp_path, exception_type):
    store, artifact, results, evidence = _case(tmp_path)
    error = exception_type("consumer stopped")
    before = _bytes(tmp_path)
    with pytest.raises(exception_type) as raised:
        with _inspection(store, artifact, results, evidence):
            raise error
    assert raised.value is error
    assert _bytes(tmp_path) == before
    for root in (store._root, results._root, evidence._semantic_root, evidence._result_store._root):
        descriptor = os.open(root / ".source-cut.lock", os.O_RDONLY)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)


def test_final_owning_result_inspection_checks_prior_leaf_after_next_relation_read(tmp_path, monkeypatch):
    store, artifact, results, evidence = _case(tmp_path)
    inspect = OnlyJsonResearchResultStore.inspect_readiness_verified
    manifest = results._target(artifact.manifest.result.research_result_plan_fingerprint) / "manifest.json"
    opened = []

    @contextmanager
    def substitute_on_next_reader(self, identity):
        with inspect(self, identity) as result:
            opened.append(True)
            if len(opened) == 2:
                original = tmp_path / "original-manifest.json"
                manifest.rename(original)
                manifest.write_bytes(original.read_bytes())
            yield result

    monkeypatch.setattr(OnlyJsonResearchResultStore, "inspect_readiness_verified", substitute_on_next_reader)
    with pytest.raises(OnlyResearchResultStoreError, match="RESEARCH_RESULT_CORRUPT"):
        with _inspection(store, artifact, results, evidence):
            pass
    assert opened == [True, True]
