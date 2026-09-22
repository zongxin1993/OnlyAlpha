from pathlib import Path

import pytest

from onlyalpha.domain.identifiers import OnlyClusterId, OnlyEngineId, OnlyRuntimeId
from onlyalpha.output import OnlyUserDataLayout


def test_user_data_layout_centralizes_run_and_cluster_paths(tmp_path: Path) -> None:
    layout = OnlyUserDataLayout(tmp_path)
    engine_id = OnlyEngineId("engine")
    assert layout.run_root(engine_id, "run-1") == tmp_path / "runs/engine/run-1"
    assert (
        layout.cluster_root(engine_id, "run-1", OnlyClusterId("alpha")) == tmp_path / "runs/engine/run-1/clusters/alpha"
    )


@pytest.mark.parametrize(
    ("engine_id", "runtime_id", "cluster_id"),
    [
        (OnlyEngineId("/tmp/escape"), OnlyRuntimeId("runtime"), OnlyClusterId("cluster")),
        (OnlyEngineId("engine"), OnlyRuntimeId("../escape"), OnlyClusterId("cluster")),
        (OnlyEngineId("engine"), OnlyRuntimeId("runtime"), OnlyClusterId(r"..\escape")),
        (OnlyEngineId("engine"), OnlyRuntimeId("C:escape"), OnlyClusterId("cluster")),
        (OnlyEngineId("engine"), OnlyRuntimeId("runtime"), OnlyClusterId("CON")),
        (OnlyEngineId("engine"), OnlyRuntimeId("runtime"), OnlyClusterId("name.")),
    ],
)
def test_runtime_admission_evidence_rejects_unsafe_path_segments(
    tmp_path: Path,
    engine_id: OnlyEngineId,
    runtime_id: OnlyRuntimeId,
    cluster_id: OnlyClusterId,
) -> None:
    with pytest.raises(ValueError, match="RUNTIME_ADMISSION_EVIDENCE_PATH_INVALID"):
        OnlyUserDataLayout(tmp_path).runtime_admission_evidence_path(
            engine_id,
            runtime_id,
            cluster_id,
            "a" * 64,
        )
