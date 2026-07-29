import json
from pathlib import Path

import pyarrow.parquet as pq

from tests.integration.test_engine_continuous_restart import only_assert_engine_restart_equivalence


def test_recovered_complete_business_result_equals_fault_free_baseline(tmp_path: Path) -> None:
    only_assert_engine_restart_equivalence(tmp_path)
    baseline_manifests = tuple((tmp_path / "baseline").rglob("artifact_manifest.json"))
    recovered_manifests = tuple(
        path for path in tmp_path.rglob("artifact_manifest.json") if not path.is_relative_to(tmp_path / "baseline")
    )
    assert len(recovered_manifests) == len(baseline_manifests) == 1
    recovered_root = recovered_manifests[0].parent
    baseline_root = baseline_manifests[0].parent
    recovered_manifest = json.loads(recovered_manifests[0].read_text(encoding="utf-8"))
    baseline_manifest = json.loads(baseline_manifests[0].read_text(encoding="utf-8"))
    assert recovered_manifest == baseline_manifest
    for descriptor in recovered_manifest["artifacts"]:
        relative_path = str(descriptor["relative_path"])
        recovered_path = recovered_root / relative_path
        baseline_path = baseline_root / relative_path
        if relative_path.endswith(".parquet"):
            assert pq.read_table(recovered_path).to_pylist() == pq.read_table(baseline_path).to_pylist()
        else:
            assert json.loads(recovered_path.read_text(encoding="utf-8")) == json.loads(
                baseline_path.read_text(encoding="utf-8")
            )
