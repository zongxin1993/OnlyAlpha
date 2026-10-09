"""Calculation V2 may not acknowledge an unreadably-durable Dataset predecessor."""

import pytest

from onlyalpha.research.calculation.errors import OnlyResearchCalculationResultStoreError
from onlyalpha.research.dataset import OnlyParquetResearchDatasetSnapshotStore
from tests.research.calculation.test_result_v2_store import _case

pytestmark = pytest.mark.contract


@pytest.mark.parametrize("existing", (False, True))
def test_calculation_commit_and_exact_reuse_require_dataset_durability(tmp_path, monkeypatch, existing):
    _, store, graph, sealed = _case(tmp_path)
    original = store.commit(sealed, graph) if existing else None
    touched = []

    def unavailable(self, identity):
        touched.append(identity)
        raise OSError("controlled Dataset acknowledgement unavailable")

    monkeypatch.setattr(OnlyParquetResearchDatasetSnapshotStore, "acknowledge_exact", unavailable)
    with pytest.raises(OnlyResearchCalculationResultStoreError, match="Dataset acknowledgement failed"):
        store.commit(sealed, graph)
    assert touched == [sealed.execution.dataset_snapshot_fingerprint]
    if original is None:
        assert not (tmp_path / "results").exists()
    else:
        assert store.load_verified(original.manifest.calculation_fingerprint) == original
    monkeypatch.undo()
    assert store.commit(sealed, graph)
