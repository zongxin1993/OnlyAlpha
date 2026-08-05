from pathlib import Path

APPLIED_LEDGER = Path("src/onlyalpha/execution/applied_projection.py")
APPLIER = Path("src/onlyalpha/execution/projection_applier.py")
PROJECTION = Path("src/onlyalpha/execution/projection.py")
TARGETS = Path("src/onlyalpha/execution/projection_targets.py")


def test_applied_projection_ledger_is_only_a_rebuildable_runtime_index() -> None:
    source = APPLIED_LEDGER.read_text(encoding="utf-8")
    assert "OnlyInMemoryAppliedRuntimeProjectionLedger" in source
    assert "Sqlite" not in source
    assert "sqlite" not in source
    assert "transaction_store" not in source


def test_recovery_state_is_a_successful_batch_outcome() -> None:
    projection = PROJECTION.read_text(encoding="utf-8")
    applier = APPLIER.read_text(encoding="utf-8")
    assert 'RECOVERED = "RECOVERED"' in projection
    assert "OnlyProjectionApplyStatus.RECOVERED" in applier
    assert "recovered.append(result)" in applier


def test_targets_do_not_cross_commit_or_business_orchestration_boundaries() -> None:
    source = TARGETS.read_text(encoding="utf-8")
    forbidden = (
        "transaction_store",
        "mark_projection_ready",
        "broker_gateway",
        "execution.reducers",
        "fee.resolver",
        "OnlyMarketRuleEngine",
        "event_bus.publish",
        "rollback",
        "compatibility",
        "validation_bypass",
        "test_only",
    )
    assert all(value not in source for value in forbidden)


def test_fee_and_settlement_targets_query_manager_authority_for_current_state() -> None:
    source = TARGETS.read_text(encoding="utf-8")
    fee = source[source.index("class OnlyFeeExecutionProjectionTarget") : source.index("def _account_snapshot")]
    settlement = source[
        source.index("class OnlySettlementExecutionProjectionTarget") : source.index(
            "class OnlyFeeExecutionProjectionTarget"
        )
    ]
    for target in (fee, settlement):
        assert ".get_execution_authority(" in target
        assert "current = projection.after" not in target


def test_recovery_decision_does_not_advance_target_event_sequences() -> None:
    source = TARGETS.read_text(encoding="utf-8")
    assert source.count("prepared.decision is _OnlyProjectionApplyDecision.APPLY") >= 6
