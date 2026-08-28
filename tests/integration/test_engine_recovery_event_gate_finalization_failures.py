from pathlib import Path

import pytest

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngineConfig
from onlyalpha.engine.engine import OnlyEngine
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.runtime.persistence.store import OnlySqliteRuntimePersistenceStore
from tests.integration.recovery_event_gate_hardening_support import (
    OnlyBeforeWriteCheckpointStoreFactory,
    OnlyReadBackMismatchCheckpointStoreFactory,
)
from tests.integration.recovery_finalization_support import (
    OnlyAfterCommitCheckpointStoreFactory,
    OnlyValidationMismatchStoreFactory,
    only_create_tail_failure,
    only_recovery_services,
)
from tests.integration.test_engine_recovery_same_bar_continuation import _same_bar_config, _services


def _checkpoint_and_pending(path: Path, engine_id: OnlyEngineId, runtime_id: object):  # type: ignore[no-untyped-def]
    state_path = OnlyUserDataLayout(path).runtime_persistence_path(engine_id, runtime_id)  # type: ignore[arg-type]
    reader = OnlySqliteRuntimePersistenceStore(state_path)
    checkpoint = reader.latest_checkpoint(runtime_id)  # type: ignore[arg-type]
    outbox = reader.outbox_records(runtime_id)  # type: ignore[arg-type]
    reader.close()
    return checkpoint, outbox


@pytest.mark.parametrize(
    ("factory", "failure_code", "commits_new_checkpoint"),
    (
        (OnlyValidationMismatchStoreFactory(), "POST_RECOVERY_AUTHORITY_VALIDATION_FAILED", False),
        (OnlyBeforeWriteCheckpointStoreFactory(), "POST_RECOVERY_CHECKPOINT_WRITE_FAILED", False),
        (
            OnlyAfterCommitCheckpointStoreFactory(),
            "POST_RECOVERY_CHECKPOINT_COMMITTED_BUT_FINALIZATION_INTERRUPTED",
            True,
        ),
        (OnlyReadBackMismatchCheckpointStoreFactory(), "POST_RECOVERY_CHECKPOINT_NOT_DURABLE", True),
    ),
)
def test_finalization_failure_matrix_is_silent_and_restartable(
    tmp_path: Path, factory: object, failure_code: str, commits_new_checkpoint: bool
) -> None:
    engine_id = OnlyEngineId(f"event-gate-{failure_code.lower()}")
    engine_a = only_create_tail_failure(tmp_path, engine_id)
    runtime_id = engine_a.runtime_sessions[0].runtime_id
    before, before_outbox = _checkpoint_and_pending(tmp_path, engine_id, runtime_id)
    assert before is not None
    assert any(not item.published for item in before_outbox)

    engine_b = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path), services=only_recovery_services(factory))
    engine_b.add_cluster(_same_bar_config(tmp_path))
    result_b = engine_b.run()
    assert result_b.status == "FAILED"
    assert any(failure_code in item for item in result_b.failures)

    after, after_outbox = _checkpoint_and_pending(tmp_path, engine_id, runtime_id)
    assert after is not None
    if commits_new_checkpoint:
        assert after.header.checkpoint_sequence > before.header.checkpoint_sequence
    else:
        assert after == before
    assert any(not item.published for item in after_outbox)

    engine_c = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path), services=_services())
    engine_c.add_cluster(_same_bar_config(tmp_path))
    result_c = engine_c.run()
    assert result_c.status == "COMPLETED", result_c.failures
