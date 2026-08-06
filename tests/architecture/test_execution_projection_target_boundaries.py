from pathlib import Path

TARGETS = Path("src/onlyalpha/execution/projection_targets.py")


def test_projection_targets_keep_replay_boundary_free_of_business_orchestration() -> None:
    source = TARGETS.read_text(encoding="utf-8")
    forbidden = (
        "execution.reducers",
        "market.runtime_rules import OnlyMarketRuleEngine",
        "fee.resolver",
        "broker.gateway",
        "event_bus.publish",
        "transaction_store",
        "mark_projection_ready",
        "committed_execution_journal",
        "uuid4",
        "service_locator",
        "rollback",
    )
    assert all(value not in source for value in forbidden)
    assert "setattr(" not in source
    assert "OnlyReferenceRuntimeProjectionTarget" not in source


def test_all_real_target_types_and_single_factory_are_present() -> None:
    source = TARGETS.read_text(encoding="utf-8")
    names = (
        "OnlyOrderExecutionProjectionTarget",
        "OnlyPositionExecutionProjectionTarget",
        "OnlyAllocationExecutionProjectionTarget",
        "OnlySettlementExecutionProjectionTarget",
        "OnlyFeeApplicationProjectionTarget",
        "OnlyAccountExecutionProjectionTarget",
        "OnlyStrategyLedgerExecutionProjectionTarget",
        "OnlyAccountCashReservationExecutionProjectionTarget",
        "OnlyStrategyCashReservationExecutionProjectionTarget",
        "OnlyRiskReservationExecutionProjectionTarget",
        "OnlyRiskExecutionProjectionTarget",
        "OnlyValuationExecutionProjectionTarget",
    )
    assert all(source.count(f"class {name}") == 1 for name in names)
    assert source.count("def only_create_generic_t0_execution_projection_targets") == 1
