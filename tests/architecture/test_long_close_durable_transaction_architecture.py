from pathlib import Path

from onlyalpha.execution import OnlyRuntimeProjectionComponent, OnlyRuntimeProjectionOrder


def test_long_close_is_routed_to_prepared_transaction_without_parallel_entrypoint() -> None:
    processor = Path("src/onlyalpha/execution/processor.py").read_text(encoding="utf-8")
    planner = Path("src/onlyalpha/execution/trade_planner.py").read_text(encoding="utf-8")
    runtime = Path("src/onlyalpha/runtime/trading_facade.py").read_text(encoding="utf-8")
    capability = Path("src/onlyalpha/execution/capability.py").read_text(encoding="utf-8")

    assert "class OnlyExecutionCapabilityResolver" in capability
    assert "def only_resolve_execution_capability(" not in capability
    assert "OnlyExecutionCapability.DURABLE_TRADE" in capability
    assert "OnlyExecutionCapability.DURABLE_TERMINAL" in capability
    assert processor.count("._execution_capability_resolver.resolve(") == 1
    assert "OnlyExecutionCapabilityResolver" not in planner
    assert "OnlyExecutionCapabilityResolver" not in runtime
    assert "trade_support.capability is OnlyExecutionCapability.DURABLE_TRADE" in processor
    assert "OnlyTradeExecutionTransactionPlanner" in planner
    assert "OnlyLongClose" not in processor + planner + runtime


def test_execution_support_and_planners_have_no_market_permission_gate() -> None:
    paths = (
        Path("src/onlyalpha/execution/capability.py"),
        Path("src/onlyalpha/execution/support.py"),
        Path("src/onlyalpha/execution/trade_planner.py"),
        Path("src/onlyalpha/execution/terminal_planner.py"),
    )
    forbidden = ("GENERIC_T0_CASH", "CN_A_SHARE_CASH", "OnlyMarketProfileId", "market_profile_id")
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert not any(item in source for item in forbidden), path


def test_planners_cannot_resolve_or_recreate_execution_support_policy() -> None:
    planner_paths = (
        Path("src/onlyalpha/execution/trade_planner.py"),
        Path("src/onlyalpha/execution/terminal_planner.py"),
        *Path("src/onlyalpha/execution/reducers").glob("*.py"),
    )
    for path in planner_paths:
        source = path.read_text(encoding="utf-8")
        assert "OnlyExecutionCapabilityResolver" not in source, path
        assert "only_resolve_execution_capability" not in source, path
    production = "\n".join(path.read_text(encoding="utf-8") for path in Path("src").rglob("*.py"))
    assert "only_resolve_execution_capability" not in production


def test_support_projection_is_pure_and_does_not_read_runtime_authorities() -> None:
    source = Path("src/onlyalpha/execution/support.py").read_text(encoding="utf-8")
    forbidden = (".manager", "onlyalpha.runtime", "Registry", "Broker", "Gateway", ".get(", ".require(")
    assert not any(item in source for item in forbidden)
    assert "only_execution_reservation_shape" in source
    assert "only_execution_support_context" in source


def test_formal_long_close_has_no_legacy_trade_path_and_terminal_has_no_fake_trade() -> None:
    processor = Path("src/onlyalpha/execution/processor.py").read_text(encoding="utf-8")
    terminal = Path("src/onlyalpha/execution/terminal_fact.py").read_text(encoding="utf-8")
    assert "_unmigrated_trade" not in processor
    assert "LEGACY_UNMIGRATED" not in processor
    assert "DURABLE_EXECUTION_REQUIRED" in processor
    assert "def _terminal_order(" not in processor
    assert "terminal_identity" in terminal
    assert "trade_id" not in terminal


def test_position_and_allocation_share_the_exact_close_cost_authority() -> None:
    state = Path("src/onlyalpha/execution/reducers/trade_state.py").read_text(encoding="utf-8")
    reducer = Path("src/onlyalpha/execution/reducers/close_cost.py").read_text(encoding="utf-8")
    authority = Path("src/onlyalpha/execution/close_cost_authority.py").read_text(encoding="utf-8")
    assert "only_reduce_average_cost_close(" not in state
    assert authority.count("only_reduce_average_cost_close(") == 1
    assert state.count("close_authority: OnlyAttributedCloseCostAuthority | None") == 2
    assert "localcontext()" in reducer
    assert "ROUND_HALF_EVEN" in reducer
    assert "fill_quantity.value == quantity_before.value" in reducer
    assert "average_open_price.value *" not in state


def test_complete_long_close_reuses_transaction_recovery_and_excludes_terminal_from_trade_result() -> None:
    processor = Path("src/onlyalpha/execution/processor.py").read_text(encoding="utf-8")
    collector = Path("src/onlyalpha/collector/backtest.py").read_text(encoding="utf-8")
    run_plan = Path("src/onlyalpha/runtime/backtest/run_plan.py").read_text(encoding="utf-8")
    recovery = Path("src/onlyalpha/execution/causal_recovery.py").read_text(encoding="utf-8")
    combined = "\n".join(path.read_text(encoding="utf-8") for path in Path("src/onlyalpha").rglob("*.py"))
    assert "_coordinate_prepared_operation(" in processor
    assert "OnlyExecutionRecoveryPhase" in recovery
    assert "OnlyCloseStore" not in combined
    assert "OnlyCloseCoordinator" not in combined
    assert "OnlyCloseRecoveryPhase" not in combined
    assert "isinstance(transaction.fact, OnlyCommittedExecutionFact)" in collector
    assert "isinstance(transaction.fact, OnlyCommittedExecutionFact)" in run_plan


def test_long_close_projection_order_is_one_fixed_global_order() -> None:
    components = (
        OnlyRuntimeProjectionComponent.ORDER,
        OnlyRuntimeProjectionComponent.POSITION,
        OnlyRuntimeProjectionComponent.ALLOCATION,
        OnlyRuntimeProjectionComponent.SETTLEMENT,
        OnlyRuntimeProjectionComponent.ORDER_FEE_ACCRUAL,
        OnlyRuntimeProjectionComponent.FEE_LEDGER,
        OnlyRuntimeProjectionComponent.ACCOUNT,
        OnlyRuntimeProjectionComponent.STRATEGY_LEDGER,
        OnlyRuntimeProjectionComponent.POSITION_RESERVATION,
        OnlyRuntimeProjectionComponent.RISK_RESERVATION,
        OnlyRuntimeProjectionComponent.RISK,
        OnlyRuntimeProjectionComponent.VALUATION,
    )

    assert tuple(OnlyRuntimeProjectionOrder[item.name] for item in components) == tuple(
        sorted(OnlyRuntimeProjectionOrder[item.name] for item in components)
    )


def test_position_reservation_is_a_formal_projection_target_and_checkpoint_participant() -> None:
    targets = Path("src/onlyalpha/execution/projection_targets.py").read_text(encoding="utf-8")
    runtime = Path("src/onlyalpha/runtime/trading_facade.py").read_text(encoding="utf-8")

    assert "class OnlyPositionReservationExecutionProjectionTarget" in targets
    assert "OnlyRuntimeProjectionComponent.POSITION_RESERVATION" in targets
    assert '"position-reservation.authority"' in runtime
