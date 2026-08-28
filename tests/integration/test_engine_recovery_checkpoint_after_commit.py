from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngineConfig
from onlyalpha.engine.engine import OnlyEngine
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.runtime.persistence.store import OnlySqliteRuntimePersistenceStore
from tests.integration.recovery_finalization_support import (
    OnlyAfterCommitCheckpointStoreFactory,
    only_create_tail_failure,
    only_recovery_services,
)
from tests.integration.test_engine_recovery_same_bar_continuation import _same_bar_config


def test_post_recovery_after_commit_exception_fails_closed_and_keeps_checkpoint(tmp_path) -> None:  # type: ignore[no-untyped-def]
    engine_id = OnlyEngineId("post-recovery-after-commit")
    first = only_create_tail_failure(tmp_path, engine_id)
    runtime_id = first.runtime_sessions[0].runtime_id
    state_path = OnlyUserDataLayout(tmp_path).runtime_persistence_path(engine_id, runtime_id)
    before = OnlySqliteRuntimePersistenceStore(state_path)
    previous = before.latest_checkpoint(runtime_id)
    assert previous is not None
    before.close()

    interrupted = OnlyEngine(
        OnlyEngineConfig(engine_id, tmp_path),
        services=only_recovery_services(OnlyAfterCommitCheckpointStoreFactory()),
    )
    interrupted.add_cluster(_same_bar_config(tmp_path))
    failed = interrupted.run()
    assert failed.status == "FAILED"
    assert any("POST_RECOVERY_CHECKPOINT_COMMITTED_BUT_FINALIZATION_INTERRUPTED" in item for item in failed.failures)

    after = OnlySqliteRuntimePersistenceStore(state_path)
    committed = after.latest_checkpoint(runtime_id)
    assert committed is not None
    assert committed.header.checkpoint_sequence > previous.header.checkpoint_sequence
    assert any(not item.published for item in after.outbox_records(runtime_id))
    after.close()
