from pathlib import Path


def test_runtime_uses_one_causal_session_and_never_skips_existing_transactions() -> None:
    source = Path("src/onlyalpha/runtime/backtest/runtime.py").read_text(encoding="utf-8")
    for removed in (
        "_in_recovery_replay",
        "_recovery_expected_update_ids",
        "_recovery_seen_update_ids",
        "get_by_update(",
        "ReadyTailRehydration",
        "recover_unprojected(",
        "_recover_market_data_tail",
    ):
        assert removed not in source
    assert "execution_processor.replay(update, session)" in source
    assert "OnlyExecutionRecoverySession | None" in source


def test_stable_bar_completion_precedes_checkpoint() -> None:
    runtime = Path("src/onlyalpha/runtime/backtest/runtime.py").read_text(encoding="utf-8")
    processor = Path("src/onlyalpha/data/processor.py").read_text(encoding="utf-8")
    after_processing = runtime[
        runtime.index("        def after_market_processing(") : runtime.index("        market_data_processor =")
    ]
    assert after_processing.index("observe_market_data_result") < after_processing.index("owned_bus.drain()")
    assert after_processing.index("owned_bus.drain()") < after_processing.index("_checkpoint_barrier(completion)")
    finish = processor[processor.index("    def _finish(") :]
    assert finish.index("_audit_store.append") < finish.index("_after_processing(update, result)")
    assert '"backtest.result-progress"' in runtime


def test_recovery_rebuilds_and_compares_the_complete_prepared_contract() -> None:
    processor = Path("src/onlyalpha/execution/processor.py").read_text(encoding="utf-8")
    session = Path("src/onlyalpha/execution/causal_recovery.py").read_text(encoding="utf-8")
    assert "self._trade_planner.prepare(planning_context)" in processor
    assert "recovery_session.require_expected(update, prepared)" in processor
    assert "prepared != expected" in session
    assert "only_prepared_execution_transaction_authority_hash" in session
    assert "only_prepared_execution_transaction_payload_hash" in session
    assert "RECOVERY_TRANSACTION_MISSING" in session
    assert "RECOVERY_PREPARED_TRANSACTION_MISMATCH" in session
    assert "RECOVERY_TRANSACTION_CAUSAL_ORDER_MISMATCH" in session


def test_result_fingerprints_share_the_canonical_business_projection() -> None:
    run_plan = Path("src/onlyalpha/runtime/backtest/run_plan.py").read_text(encoding="utf-8")
    projection = Path("src/onlyalpha/result/business_projection.py").read_text(encoding="utf-8")
    assert run_plan.count("only_backtest_business_projection(result)") == 1
    assert "determinism_fingerprint=fingerprint, result_fingerprint=fingerprint" in run_plan
    assert "execution_recoveries" not in projection
    assert "cluster_results" in projection
    assert "diagnostics" in projection


def test_recovery_lifecycle_does_not_repeat_normal_start() -> None:
    runtime = Path("src/onlyalpha/runtime/backtest/runtime.py").read_text(encoding="utf-8")
    manager = Path("src/onlyalpha/cluster/manager.py").read_text(encoding="utf-8")
    recovery = runtime[runtime.index("    def _recover_runtime(") : runtime.index("    def _register_cluster")]
    assert "start_all()" not in recovery
    assert "enter_recovery_all()" in recovery
    assert "complete_recovery_all()" in recovery
    assert "on_recovery_enter" in manager
    assert "on_recovery_complete" in manager
