"""Owning acknowledgements cannot return proof for a substituted publication tree."""

import fcntl
import os

import pytest

from onlyalpha.research.artifact.errors import OnlyResearchArtifactError
from onlyalpha.research.calculation.errors import OnlyResearchCalculationError, OnlyResearchCalculationResultStoreError
from onlyalpha.research.job import OnlyResearchJobError, OnlyResearchJobExecutor
from onlyalpha.research.result import OnlyResearchResultStoreError
from tests.research.artifact.test_calculation_v2 import _publication
from tests.research.calculation.test_execution_evidence_v2 import _case as evidence_case
from tests.research.calculation.test_result_v2_store import _case as calculation_case
from tests.research.calculation.test_runtime_execution_provenance import _context
from tests.research.job.support import readiness_job_case
from tests.research.result.test_readiness_composition import _composition

pytestmark = pytest.mark.contract


def _authority(tmp_path, family):
    if family == "calculation":
        _, store, graph, sealed = calculation_case(tmp_path)
        result = store.commit(sealed, graph)
        target = store._target(result.manifest.calculation_fingerprint)

        def action():
            return store.acknowledge_exact(
                result.manifest.calculation_fingerprint, result.manifest.calculation_result_fingerprint
            )

        error = OnlyResearchCalculationResultStoreError
    elif family == "evidence":
        _, _, _, sealed, result, store = evidence_case(tmp_path)
        evidence = store._publish_verified(sealed, result)
        target = store._target(evidence.evidence_fingerprint)

        def action():
            return store._acknowledge(evidence)

        error = OnlyResearchCalculationError
    elif family == "job":
        plan, calculation, legacy, results, store = readiness_job_case(tmp_path)
        context = _context(calculation, plan.calculation_graph)
        job = OnlyResearchJobExecutor(
            calculation,
            legacy,
            object(),
            readiness_result_store=results,
            readiness_execution_evidence_store=store,
            runtime_execution_context=context,
        )
        outcome = job.execute(plan)
        target = store._target(outcome.calculation_execution_evidence_fingerprint)

        def action():
            return job.execute(plan)

        error = OnlyResearchJobError
    elif family == "artifact":
        publish, store, _, _, _, _ = _publication(tmp_path)
        artifact = publish()
        target = store._target(artifact.manifest.artifact_content_fingerprint)
        action = publish
        error = OnlyResearchArtifactError
    else:
        plan, assembler, store, _ = _composition(tmp_path)
        result = assembler.assemble(plan)
        store.commit(result)
        target = store._target(plan.fingerprint)

        def action():
            return store.commit(result)

        error = OnlyResearchResultStoreError
    return target, action, error


@pytest.mark.parametrize("family", ("calculation", "evidence", "result", "job", "artifact"))
@pytest.mark.parametrize("mutation", ("prefix", "target", "manifest", "extra_file", "extra_directory"))
def test_namespace_substitution_during_owned_sync_cannot_report_success(tmp_path, monkeypatch, family, mutation):
    target, action, error = _authority(tmp_path, family)
    identity = (target.stat().st_dev, target.stat().st_ino)
    sync, touched = os.fsync, []

    def substitute(descriptor):
        sync(descriptor)
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != identity or touched:
            return
        touched.append(mutation)
        if mutation == "extra_file":
            (target / "unexpected.json").write_text("{}")
        elif mutation == "extra_directory":
            (target / "unexpected").mkdir()
        else:
            manifest_name = "artifact_manifest.json" if family == "artifact" else "manifest.json"
            path = {"prefix": target.parent, "target": target, "manifest": target / manifest_name}[mutation]
            moved = tmp_path / "substituted-publication"
            path.rename(moved)
            if mutation == "manifest":
                path.write_bytes(moved.read_bytes())
            else:
                path.symlink_to(moved, target_is_directory=True)

    monkeypatch.setattr(os, "fsync", substitute)
    with pytest.raises(error):
        action()
    assert touched == [mutation]


@pytest.mark.parametrize("family", ("calculation", "evidence", "result", "job", "artifact"))
def test_leaf_replacement_immediately_after_file_sync_invalidates_acknowledgement(tmp_path, monkeypatch, family):
    target, action, error = _authority(tmp_path, family)
    path = target / ("artifact_manifest.json" if family == "artifact" else "manifest.json")
    identity = (path.stat().st_dev, path.stat().st_ino)
    sync, touched = os.fsync, []

    def substitute(descriptor):
        sync(descriptor)
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) == identity and not touched:
            touched.append(path)
            moved = tmp_path / "substituted-manifest.json"
            path.rename(moved)
            path.write_bytes(moved.read_bytes())

    monkeypatch.setattr(os, "fsync", substitute)
    with pytest.raises(error):
        action()
    assert touched == [path]


@pytest.mark.parametrize("family", ("calculation", "artifact"))
def test_nested_partition_replacement_cannot_borrow_the_original_files_durability(tmp_path, monkeypatch, family):
    target, action, error = _authority(tmp_path, family)
    path = next(target.rglob("*.parquet"))
    identity = (path.stat().st_dev, path.stat().st_ino)
    sync, touched = os.fsync, []

    def substitute(descriptor):
        sync(descriptor)
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) == identity and not touched:
            touched.append(path)
            moved = tmp_path / "substituted-partition.parquet"
            path.rename(moved)
            path.write_bytes(moved.read_bytes())

    monkeypatch.setattr(os, "fsync", substitute)
    with pytest.raises(error):
        action()
    assert touched == [path]


@pytest.mark.parametrize("family", ("result", "evidence"))
def test_owning_auxiliary_namespace_substitution_also_invalidates_acknowledgement(tmp_path, monkeypatch, family):
    target, action, error = _authority(tmp_path, family)
    path = (
        tmp_path / "compositions" / ".source-cut.lock"
        if family == "result"
        else target.parent.parent.parent / ".staging"
    )
    identity = (path.stat().st_dev, path.stat().st_ino)
    sync, touched = os.fsync, []

    def substitute(descriptor):
        sync(descriptor)
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) == identity and not touched:
            touched.append(path)
            moved = tmp_path / "substituted-auxiliary-entry"
            path.rename(moved)
            path.symlink_to(moved, target_is_directory=family == "evidence")

    monkeypatch.setattr(os, "fsync", substitute)
    with pytest.raises(error):
        action()
    assert touched == [path]


@pytest.mark.parametrize("entry", ("result_acknowledge", "result_commit_reuse", "artifact_publish"))
def test_result_barrier_cannot_be_replaced_before_acknowledgement_binds_its_tree(tmp_path, monkeypatch, entry):
    if entry == "artifact_publish":
        publish, _, _, _, _, _ = _publication(tmp_path)
        artifact = publish()
        calculation_id = artifact.manifest.calculations[0].calculation_fingerprint
        calculation = tmp_path / "calculations" / "v2" / "sha256" / calculation_id[:2] / calculation_id
        path = tmp_path / "results" / ".source-cut.lock"
        action = publish
        error = OnlyResearchArtifactError
    else:
        plan, assembler, store, calculations = _composition(tmp_path)
        result = assembler.assemble(plan)
        store.commit(result)
        calculation = calculations._target(result.manifest.calculation_results[0].calculation_fingerprint)
        path = tmp_path / "compositions" / ".source-cut.lock"

        def action():
            if entry == "result_acknowledge":
                return store.acknowledge_exact(plan.fingerprint, result.manifest.research_result_fingerprint)
            return store.commit(result)

        error = OnlyResearchResultStoreError
    identity = (calculation.stat().st_dev, calculation.stat().st_ino)
    moved = tmp_path / "held-original-source-cut.lock"
    sync, touched = os.fsync, []

    def substitute(descriptor):
        sync(descriptor)
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != identity or touched:
            return
        with path.open("rb") as probe:
            try:
                fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass  # The original publication barrier really is held.
            else:
                fcntl.flock(probe.fileno(), fcntl.LOCK_UN)
                return
        path.rename(moved)
        path.write_bytes(moved.read_bytes())
        with path.open("rb") as concurrent_capture:
            fcntl.flock(concurrent_capture.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            touched.append("replacement_admitted_exclusive_capture")
            fcntl.flock(concurrent_capture.fileno(), fcntl.LOCK_UN)

    monkeypatch.setattr(os, "fsync", substitute)
    with pytest.raises(error):
        action()
    assert touched == ["replacement_admitted_exclusive_capture"]
    monkeypatch.undo()
    # Restoring the original lock binding permits exact re-entry, not a new
    # publication identity or reconstruction of any upstream fact.
    path.unlink()
    moved.rename(path)
    assert action()
