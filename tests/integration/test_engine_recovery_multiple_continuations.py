from dataclasses import replace
from pathlib import Path

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngineConfig
from onlyalpha.engine.engine import OnlyEngine
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.result import only_backtest_business_projection
from onlyalpha.runtime.persistence.store import OnlySqliteRuntimePersistenceStore
from tests.integration.test_engine_recovery_same_bar_continuation import (
    _same_bar_config,
    _services,
)


def test_engine_commits_three_contiguous_continuations_in_recovery_boundary(tmp_path: Path) -> None:
    baseline_config = _same_bar_config(tmp_path)
    initial = dict(baseline_config.cluster.scenario_actions[0])
    continuation = dict(baseline_config.cluster.scenario_actions[1])
    actions = (initial,) + tuple(
        {**continuation, "action_id": f"POSITION_CONTINUATION_{index}"} for index in range(1, 4)
    )
    config = replace(baseline_config, cluster=replace(baseline_config.cluster, scenario_actions=actions))
    engine_id = OnlyEngineId("three-recovery-continuations")

    engine_a = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path), services=_services(with_fault=True))
    engine_a.add_cluster(config)
    assert engine_a.run().status == "FAILED"

    engine_b = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path), services=_services())
    engine_b.add_cluster(config)
    recovered = engine_b.run()
    assert recovered.status == "COMPLETED", recovered.failures
    diagnostic = engine_b.runtime_sessions[0].runtime.runtime_recovery_diagnostics[-1]
    assert diagnostic.continuation_transaction_count == 6

    runtime_id = engine_b.runtime_sessions[0].runtime_id
    state_path = OnlyUserDataLayout(tmp_path).runtime_persistence_path(engine_id, runtime_id)
    reader = OnlySqliteRuntimePersistenceStore(state_path)
    transactions = reader.records(runtime_id)
    assert tuple(item.execution_sequence for item in transactions[:8]) == tuple(range(1, 9))
    assert all(item.projection_ready for item in transactions[:8])
    reader.close()

    baseline_root = tmp_path / "baseline"
    baseline_config = _same_bar_config(baseline_root)
    baseline_initial = dict(baseline_config.cluster.scenario_actions[0])
    baseline_continuation = dict(baseline_config.cluster.scenario_actions[1])
    baseline_actions = (baseline_initial,) + tuple(
        {**baseline_continuation, "action_id": f"POSITION_CONTINUATION_{index}"} for index in range(1, 4)
    )
    baseline_engine = OnlyEngine(OnlyEngineConfig(engine_id, baseline_root), services=_services())
    baseline_engine.add_cluster(
        replace(baseline_config, cluster=replace(baseline_config.cluster, scenario_actions=baseline_actions))
    )
    baseline = baseline_engine.run()
    assert baseline.status == "COMPLETED"
    assert recovered.runtime_results[0].orders == baseline.runtime_results[0].orders
    assert recovered.runtime_results[0].trades == baseline.runtime_results[0].trades
    assert only_backtest_business_projection(recovered.runtime_results[0]) == only_backtest_business_projection(
        baseline.runtime_results[0]
    )
