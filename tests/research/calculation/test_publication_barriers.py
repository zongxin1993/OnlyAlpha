"""Actual V2 publish/re-entry/ack paths participate in owning exclusion."""

from __future__ import annotations

import fcntl
import os

import pytest

from tests.research.artifact.test_calculation_v2 import _publication
from tests.research.calculation.test_result_v2_store import _case

pytestmark = pytest.mark.contract


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
