"""Actual V2 publish/re-entry/ack paths participate in owning exclusion."""

from __future__ import annotations

import fcntl
import os

import pytest

from tests.research.artifact.test_calculation_v2 import _publication
from tests.research.calculation.test_result_v2_store import _case

pytestmark = pytest.mark.contract


def test_calculation_incomplete_graph_does_not_provision_publication_metadata(tmp_path):
    from onlyalpha.research.calculation.errors import OnlyResearchCalculationResultStoreError

    _, store, _, sealed = _case(tmp_path)
    with pytest.raises(OnlyResearchCalculationResultStoreError, match="RESULT_INVALID"):
        store.commit(sealed, None)
    assert not (tmp_path / "results").exists()


@pytest.mark.parametrize("boundary", ["source", "audit_time"])
def test_calculation_parent_substitution_never_creates_root_through_replacement(tmp_path, monkeypatch, boundary):
    from onlyalpha.research.calculation.errors import OnlyResearchCalculationResultStoreError
    from onlyalpha.research.source_cut import OnlySourceCutError
    from tests.research.calculation.test_result_v2_store import AUDIT

    parent = tmp_path / "owner"
    _, store, graph, sealed = _case(parent)
    replacement = tmp_path / "unrelated"
    replacement.mkdir()
    sentinel = replacement / "retained"
    sentinel.write_bytes(b"original unrelated bytes")

    def substitute():
        parent.rename(tmp_path / "original-owner")
        parent.symlink_to(replacement, target_is_directory=True)

    if boundary == "source":
        source = store._source

        def changed_source(*args):
            axes = source(*args)
            substitute()
            return axes

        monkeypatch.setattr(store, "_source", changed_source)
    else:

        def changed_audit():
            substitute()
            return AUDIT

        monkeypatch.setattr(store, "_audit_time", changed_audit)
    with pytest.raises((OnlyResearchCalculationResultStoreError, OnlySourceCutError)) as error:
        store.commit(sealed, graph)
    assert {entry.name for entry in replacement.iterdir()} == {"retained"}
    assert sentinel.read_bytes() == b"original unrelated bytes"
    assert not (tmp_path / "original-owner" / "results").exists()
    assert isinstance(error.value, OnlyResearchCalculationResultStoreError)
    assert error.value.code == "RESULT_COMMIT_FAILED"


@pytest.mark.parametrize("owner", ["parent", "root"])
def test_calculation_root_binding_handover_never_selects_replacement_owner(tmp_path, monkeypatch, owner):
    from onlyalpha.research._durability import _OnlyBoundPublicationTree
    from onlyalpha.research.calculation.errors import OnlyResearchCalculationResultStoreError

    parent = tmp_path / "owner"
    _, store, graph, sealed = _case(parent)
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    replacement_root = replacement / "results"
    replacement_root.mkdir()
    (replacement_root / "retained").write_bytes(b"unrelated original")
    create = _OnlyBoundPublicationTree.create_directory
    changed = []

    def substitute_after_create(tree, path):
        descriptor = create(tree, path)
        if path == store._root and not changed:
            changed.append(True)
            if owner == "parent":
                parent.rename(tmp_path / "original-owner")
                replacement.rename(parent)
            else:
                store._root.rename(tmp_path / "original-root")
                replacement_root.rename(store._root)
        return descriptor

    monkeypatch.setattr(_OnlyBoundPublicationTree, "create_directory", substitute_after_create)
    with pytest.raises(OnlyResearchCalculationResultStoreError) as error:
        store.commit(sealed, graph)
    assert changed == [True]
    assert {entry.name for entry in store._root.iterdir()} == {"retained"}
    assert (store._root / "retained").read_bytes() == b"unrelated original"
    assert error.value.code == "RESULT_COMMIT_FAILED"


@pytest.mark.parametrize("owner", ["calculation", "evidence", "artifact"])
@pytest.mark.parametrize("action", ["new", "reuse", "acknowledge"])
def test_v2_writes_hold_publication_lock_through_sync(tmp_path, monkeypatch, owner, action):
    if owner == "calculation":
        _, store, graph, sealed = _case(tmp_path)
        root = tmp_path / "results"
        module = "onlyalpha.research.calculation.result_v2_store"
        hook = "_sync_directory"

        def publish():
            return store.commit(sealed, graph)

        def acknowledge():
            result = store.load_verified(sealed.execution.calculation_fingerprint)
            return store.acknowledge_exact(
                result.manifest.calculation_fingerprint, result.manifest.calculation_result_fingerprint
            )

    else:
        publish_artifact, artifact_store, _, _, _, evidence = _publication(tmp_path)
        if owner == "evidence":
            root = tmp_path / "semantic"
            module = "onlyalpha.research.calculation.execution_evidence_v2"
            hook = "_sync_directory"
            # Obtain an authentic sealed execution from the same owning Dataset.
            from onlyalpha.research.calculation.backend import OnlyResearchCalculationBackendResolver
            from onlyalpha.research.calculation.execution import OnlyResearchCalculationExecutor
            from tests.research.calculation.test_execution_readiness_v2 import PUBLICATION, _registry

            calculations = evidence._result_store
            calculation = calculations.load_verified(evidence._iter_retained()[0].calculation_fingerprint)
            sealed = OnlyResearchCalculationExecutor(
                calculations._dataset_store, OnlyResearchCalculationBackendResolver(_registry())
            )._execute_verified_v2(
                calculation.manifest.dataset_snapshot_fingerprint, calculation.manifest.calculation_graph, PUBLICATION
            )

            def publish():
                return evidence._publish_verified(sealed, calculation)

            def acknowledge():
                retained = publish()
                return evidence.acknowledge_exact(retained.evidence_fingerprint)

        else:
            root = tmp_path / "artifacts"
            module = "onlyalpha.research.artifact.calculation_v2_store"
            hook = "_sync_package"
            publish = publish_artifact

            def acknowledge():
                artifact = publish_artifact()
                return artifact_store._acknowledge(
                    artifact.manifest.artifact_content_fingerprint, artifact.manifest.result.research_result_fingerprint
                )

    # Explicit provisioning is separate from read-only inspection. A real lock
    # already exists so failure proves missing exclusion, not missing lock setup.
    root.mkdir(exist_ok=True)
    (root / ".source-cut.lock").touch()
    if action != "new":
        publish()
    import importlib

    owning_module = importlib.import_module(module)
    synchronize = getattr(owning_module, hook)
    observed = []

    def checked_sync(*args, **kwargs):
        descriptor = os.open(root / ".source-cut.lock", os.O_RDONLY)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            observed.append(True)
        finally:
            os.close(descriptor)
        return synchronize(*args, **kwargs)

    monkeypatch.setattr(owning_module, hook, checked_sync)
    (acknowledge if action == "acknowledge" else publish)()
    assert observed
    descriptor = os.open(root / ".source-cut.lock", os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(descriptor)
