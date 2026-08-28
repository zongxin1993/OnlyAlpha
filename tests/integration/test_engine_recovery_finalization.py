from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngineConfig
from onlyalpha.engine.engine import OnlyEngine
from onlyalpha.runtime.recovery.finalizer import OnlyRuntimeRecoveryFinalizationPhase
from tests.integration.recovery_finalization_support import only_create_tail_failure
from tests.integration.test_engine_recovery_same_bar_continuation import _same_bar_config, _services


def test_engine_recovery_requires_verified_finalization_before_running(tmp_path) -> None:  # type: ignore[no-untyped-def]
    engine_id = OnlyEngineId("recovery-finalization")
    only_create_tail_failure(tmp_path, engine_id)
    recovered = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path), services=_services())
    recovered.add_cluster(_same_bar_config(tmp_path))
    result = recovered.run()
    assert result.status == "COMPLETED", result.failures
    runtime = recovered.runtime_sessions[0].runtime
    assert runtime.post_recovery_validation_reports[-1].passed
    assert runtime._runtime_recovery_finalizer.phase is OnlyRuntimeRecoveryFinalizationPhase.COMPLETED
