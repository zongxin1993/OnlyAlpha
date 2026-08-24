import sqlite3
from pathlib import Path

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.output import OnlyUserDataLayout
from tests.integration.test_engine_continuous_restart import _sqlite_config


def test_corrupt_checkpoint_component_fails_fast_without_falling_back(tmp_path: Path) -> None:
    config = _sqlite_config(tmp_path)
    engine_id = OnlyEngineId("checkpoint-corruption")
    engine_a = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path))
    engine_a.add_cluster(config)
    assert engine_a.run().status == "COMPLETED"
    runtime_id = engine_a.runtime_sessions[0].runtime_id
    path = OnlyUserDataLayout(tmp_path).runtime_persistence_path(engine_id, runtime_id)
    with sqlite3.connect(path) as connection:
        latest = connection.execute(
            "SELECT MAX(checkpoint_sequence) FROM runtime_checkpoints WHERE runtime_id=?",
            (str(runtime_id),),
        ).fetchone()
        assert latest is not None and latest[0] is not None
        connection.execute(
            "UPDATE runtime_checkpoint_components SET payload='{}' "
            "WHERE runtime_id=? AND checkpoint_sequence=? AND component_id=("
            "SELECT MIN(component_id) FROM runtime_checkpoint_components "
            "WHERE runtime_id=? AND checkpoint_sequence=?)",
            (str(runtime_id), int(latest[0]), str(runtime_id), int(latest[0])),
        )

    engine_b = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path))
    engine_b.add_cluster(config)
    result = engine_b.run()
    assert result.status == "FAILED"
    assert result.runtime_results == ()
