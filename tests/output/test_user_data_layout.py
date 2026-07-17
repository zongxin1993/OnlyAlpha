from pathlib import Path

from onlyalpha.domain.identifiers import OnlyClusterId, OnlyEngineId
from onlyalpha.output import OnlyUserDataLayout


def test_user_data_layout_centralizes_run_and_cluster_paths(tmp_path: Path) -> None:
    layout = OnlyUserDataLayout(tmp_path)
    engine_id = OnlyEngineId("engine")
    assert layout.run_root(engine_id, "run-1") == tmp_path / "runs/engine/run-1"
    assert (
        layout.cluster_root(engine_id, "run-1", OnlyClusterId("alpha")) == tmp_path / "runs/engine/run-1/clusters/alpha"
    )
