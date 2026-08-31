import json

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngineConfig
from onlyalpha.engine.engine import OnlyEngine
from onlyalpha.result import only_backtest_business_projection
from tests.integration.recovery_finalization_support import (
    OnlyAfterCommitCheckpointStoreFactory,
    only_create_tail_failure,
    only_recovery_services,
)
from tests.integration.test_engine_recovery_same_bar_continuation import _same_bar_config, _services


def test_engine_a_b_c_restart_uses_committed_post_recovery_checkpoint_once(tmp_path) -> None:  # type: ignore[no-untyped-def]
    engine_id = OnlyEngineId("three-stage-recovery-finalization")
    only_create_tail_failure(tmp_path, engine_id)

    engine_b = OnlyEngine(
        OnlyEngineConfig(engine_id, tmp_path),
        services=only_recovery_services(OnlyAfterCommitCheckpointStoreFactory()),
    )
    engine_b.add_cluster(_same_bar_config(tmp_path))
    assert engine_b.run().status == "FAILED"

    engine_c = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path), services=_services())
    engine_c.add_cluster(_same_bar_config(tmp_path))
    recovered = engine_c.run()
    assert recovered.status == "COMPLETED", recovered.failures

    baseline_root = tmp_path / "baseline"
    baseline = OnlyEngine(OnlyEngineConfig(engine_id, baseline_root), services=_services())
    baseline.add_cluster(_same_bar_config(baseline_root))
    expected = baseline.run()
    assert expected.status == "COMPLETED"
    assert only_backtest_business_projection(recovered.runtime_results[0]) == only_backtest_business_projection(
        expected.runtime_results[0]
    )
    assert recovered.runtime_results[0].result_fingerprint == expected.runtime_results[0].result_fingerprint
    assert recovered.runtime_results[0].orders == expected.runtime_results[0].orders
    assert recovered.runtime_results[0].trades == expected.runtime_results[0].trades
    assert recovered.runtime_results[0].facts.signals == expected.runtime_results[0].facts.signals
    recovered_manifests = tuple(
        path
        for path in tmp_path.rglob("artifact_manifest.json")
        if not path.is_relative_to(tmp_path / "baseline")
        and json.loads(path.read_text(encoding="utf-8")).get("result_fingerprint")
        == recovered.runtime_results[0].result_fingerprint
    )
    baseline_manifests = tuple((tmp_path / "baseline").rglob("artifact_manifest.json"))
    assert len(recovered_manifests) == len(baseline_manifests) == 1
    assert json.loads(recovered_manifests[0].read_text(encoding="utf-8")) == json.loads(
        baseline_manifests[0].read_text(encoding="utf-8")
    )
