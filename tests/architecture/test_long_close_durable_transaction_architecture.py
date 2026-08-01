from pathlib import Path

from onlyalpha.execution import OnlyExecutionProjectionComponent, OnlyExecutionProjectionOrder


def test_long_close_is_routed_to_prepared_transaction_without_parallel_entrypoint() -> None:
    processor = Path("src/onlyalpha/execution/processor.py").read_text(encoding="utf-8")
    planner = Path("src/onlyalpha/execution/trade_planner.py").read_text(encoding="utf-8")
    runtime = Path("src/onlyalpha/runtime/backtest/runtime.py").read_text(encoding="utf-8")
    capability = Path("src/onlyalpha/execution/capability.py").read_text(encoding="utf-8")

    assert "def only_resolve_execution_capability(" in capability
    assert "OnlyExecutionCapability.DURABLE_TRADE" in capability
    assert "OnlyExecutionCapability.DURABLE_TERMINAL" in capability
    assert "only_resolve_execution_capability(" in processor
    assert "only_resolve_execution_capability(" in planner
    assert "only_resolve_execution_capability(" in runtime
    assert "if isinstance(update, OnlyBrokerTradeUpdate) and self._uses_prepared_trade_path" in processor
    assert "OnlyTradeExecutionTransactionPlanner" in planner
    assert "OnlyLongClose" not in processor + planner + runtime


def test_formal_long_close_legacy_methods_are_guarded_and_terminal_has_no_fake_trade() -> None:
    processor = Path("src/onlyalpha/execution/processor.py").read_text(encoding="utf-8")
    terminal = Path("src/onlyalpha/execution/terminal_fact.py").read_text(encoding="utf-8")
    assert "DURABLE_TRADE_REQUIRED" in processor
    assert "DURABLE_TERMINAL_REQUIRED" in processor
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
        OnlyExecutionProjectionComponent.ORDER,
        OnlyExecutionProjectionComponent.POSITION,
        OnlyExecutionProjectionComponent.ALLOCATION,
        OnlyExecutionProjectionComponent.SETTLEMENT,
        OnlyExecutionProjectionComponent.ORDER_FEE_ACCRUAL,
        OnlyExecutionProjectionComponent.FEE,
        OnlyExecutionProjectionComponent.ACCOUNT,
        OnlyExecutionProjectionComponent.STRATEGY_LEDGER,
        OnlyExecutionProjectionComponent.POSITION_RESERVATION,
        OnlyExecutionProjectionComponent.RISK_RESERVATION,
        OnlyExecutionProjectionComponent.RISK,
        OnlyExecutionProjectionComponent.VALUATION,
    )

    assert tuple(OnlyExecutionProjectionOrder[item.name] for item in components) == tuple(
        sorted(OnlyExecutionProjectionOrder[item.name] for item in components)
    )


def test_position_reservation_is_a_formal_projection_target_and_checkpoint_participant() -> None:
    targets = Path("src/onlyalpha/execution/projection_targets.py").read_text(encoding="utf-8")
    runtime = Path("src/onlyalpha/runtime/backtest/runtime.py").read_text(encoding="utf-8")

    assert "class OnlyPositionReservationExecutionProjectionTarget" in targets
    assert "OnlyExecutionProjectionComponent.POSITION_RESERVATION" in targets
    assert '"position-reservation.authority"' in runtime
