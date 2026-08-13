from pathlib import Path


def test_execution_recovery_does_not_depend_on_runtime_boundary_types() -> None:
    execution = Path("src/onlyalpha/execution/causal_recovery.py").read_text(encoding="utf-8")
    assert "onlyalpha.runtime" not in execution
    assert "OnlyBacktest" not in execution
    assert "boundary_complete" not in execution
    assert "complete_boundary" not in execution
    assert "def require_expected" not in execution
    assert "def require_complete" not in execution


def test_runtime_owns_one_active_driver_neutral_execution_recovery_session() -> None:
    runtime = Path("src/onlyalpha/runtime/trading_facade.py").read_text(encoding="utf-8")
    assert "self._backtest_recovery_session: OnlyBacktestRecoverySession | None" in runtime
    assert "self._execution_recovery_session: OnlyExecutionRecoverySession | None" in runtime
    assert "execution_processor.replay(update, execution_session)" in runtime
    assert "backtest_session.execution_session" in runtime
    assert "self._backtest_recovery_session is not None" in runtime


def test_processor_selects_persisted_and_continuation_coordination_paths() -> None:
    processor = Path("src/onlyalpha/execution/processor.py").read_text(encoding="utf-8")
    assert "recovery_session.decide(update, prepared)" in processor
    assert "OnlyExecutionRecoveryDecisionKind.REHYDRATE_READY" in processor
    assert "OnlyExecutionRecoveryDecisionKind.RECOVER_UNPROJECTED" in processor
    assert "OnlyExecutionRecoveryDecisionKind.COMMIT_CONTINUATION" in processor
    continuation = processor[
        processor.index(
            "else:\n                coordination = self._execution_commit_coordinator.commit("
        ) : processor.index("        else:\n            coordination = self._execution_commit_coordinator.commit(")
    ]
    assert "rehydrate_existing" not in continuation
    assert "recover_existing" not in continuation


def test_replay_service_enters_exact_boundary_and_never_completes_it() -> None:
    replay = Path("src/onlyalpha/runtime/backtest/recovery_replay.py").read_text(encoding="utf-8")
    assert "backtest_session.enter_boundary(OnlyBacktestRecoveryBoundary.from_record(record))" in replay
    assert "backtest_session.phase is OnlyBacktestRecoveryPhase.BOUNDARY_COMPLETED" in replay
    assert "complete_boundary" not in replay
    assert "session.complete" not in replay


def test_boundary_completion_is_after_progress_and_event_drain_before_checkpoint() -> None:
    runtime = Path("src/onlyalpha/runtime/trading_facade.py").read_text(encoding="utf-8")
    callback = runtime[
        runtime.index("        def after_market_processing(") : runtime.index("        market_data_processor =")
    ]
    progress = callback.index("observe_market_data_result")
    drain = callback.index("owned_bus.drain()")
    completion = callback.index("recovery_session.observe_completion(completion)")
    checkpoint = callback.index("self._checkpoint_barrier(completion)")
    assert progress < drain < completion < checkpoint


def test_recovery_order_commands_are_enabled_without_production_fault_switches() -> None:
    runtime = Path("src/onlyalpha/runtime/trading_facade.py").read_text(encoding="utf-8")
    permission = runtime[
        runtime.index("    def _order_commands_enabled(") : runtime.index("    def _begin_direct_execution_events(")
    ]
    assert "OnlyRuntimeState.RECOVERING" in permission
    assert "OnlyClusterState.RECOVERING" in permission
    for forbidden in ("fault_injection", "recovery_fault", "force_recovery"):
        assert forbidden not in runtime
