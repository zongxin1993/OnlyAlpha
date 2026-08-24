from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.runtime.persistence.store import OnlySqliteRuntimePersistenceStore
from tests.integration.recovery_finalization_support import (
    OnlyValidationMismatchStoreFactory,
    only_create_tail_failure,
    only_recovery_services,
)
from tests.integration.test_engine_recovery_same_bar_continuation import _same_bar_config


def test_validation_failure_keeps_checkpoint_and_blocks_resume(tmp_path) -> None:  # type: ignore[no-untyped-def]
    engine_id = OnlyEngineId("recovery-validation-failure")
    first = only_create_tail_failure(tmp_path, engine_id)
    runtime_id = first.runtime_sessions[0].runtime_id
    path = OnlyUserDataLayout(tmp_path).runtime_persistence_path(engine_id, runtime_id)
    reader = OnlySqliteRuntimePersistenceStore(path)
    before = reader.latest_checkpoint(runtime_id)
    assert before is not None
    reader.close()

    failed_engine = OnlyEngine(
        OnlyEngineConfig(engine_id, tmp_path),
        services=only_recovery_services(OnlyValidationMismatchStoreFactory()),
    )
    failed_engine.add_cluster(_same_bar_config(tmp_path))
    failed = failed_engine.run()
    assert failed.status == "FAILED"
    assert any("POST_RECOVERY_AUTHORITY_VALIDATION_FAILED" in item for item in failed.failures)
    reopened = OnlySqliteRuntimePersistenceStore(path)
    assert reopened.latest_checkpoint(runtime_id) == before
    assert any(not item.published for item in reopened.outbox_records(runtime_id))
    reopened.close()
