"""Real-Manager Generic T0 Cash parity harness."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from onlyalpha.broker import OnlyBrokerGatewayId, OnlyBrokerTradeUpdate, OnlyBrokerUpdateId
from onlyalpha.domain.enums import OnlyLiquiditySide
from onlyalpha.domain.execution import OnlyOrderFill
from onlyalpha.domain.identifiers import OnlyEngineId, OnlyOrderId, OnlyPositionId, OnlyTradeId, OnlyVenueTradeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha.execution import (
    OnlyAllocationCreationAuthority,
    OnlyFeeExecutionState,
    OnlyFeeInstructionReplay,
    OnlyFeeRecordReplay,
    OnlyPositionCreationAuthority,
    OnlyPreparedRuntimeTransaction,
    OnlyRuntimeProjection,
    OnlyRuntimeProjectionComponent,
    OnlyTradeExecutionPlanningContext,
    OnlyTradeExecutionTransactionPlanner,
    OnlyValuationExecutionState,
    only_account_cash_reservation_execution_state,
    only_account_execution_state,
    only_allocation_execution_state,
    only_capture_execution_fill_authority,
    only_order_execution_state,
    only_position_execution_state,
    only_position_reservation_execution_state,
    only_risk_execution_state,
    only_risk_reservation_execution_state,
    only_strategy_cash_reservation_execution_state,
    only_strategy_ledger_execution_state,
)
from onlyalpha.execution.authority_state import only_settlement_execution_state
from onlyalpha.fee import OnlyFeeConfigurationMode
from onlyalpha.fee.resolver import OnlyFeeResolverConfig
from onlyalpha.market.models import OnlyMarketPositionMode, OnlyMarketProfileId
from onlyalpha.market.runtime_rules import OnlyTradeApplicationRequest
from onlyalpha.position.enums import OnlyPositionMode
from onlyalpha.position.identifiers import OnlyPositionAllocationId
from tests.integration_demo.environment import DAY_ONE, OnlyIntegrationEnvironment

from .manager_authority_digest import OnlyTestRuntimeAuthorityDigest, only_test_runtime_authority_digest


@dataclass(frozen=True, slots=True)
class OnlyTestGenericT0Scenario:
    name: str
    fee_enabled: bool = True
    fill_price: str = "10.00"
    existing_position: bool = False
    virtual_broker: bool = True


@dataclass(frozen=True, slots=True)
class OnlyTestGenericT0ParityResult:
    scenario: OnlyTestGenericT0Scenario
    context: OnlyTradeExecutionPlanningContext
    prepared: OnlyPreparedRuntimeTransaction
    legacy_result: object
    manager_before: OnlyTestRuntimeAuthorityDigest
    manager_after: OnlyTestRuntimeAuthorityDigest
    planner_before: OnlyTestRuntimeAuthorityDigest
    planner_after: OnlyTestRuntimeAuthorityDigest
    legacy_states: tuple[tuple[OnlyRuntimeProjectionComponent, object], ...]


def only_test_generic_t0_manager_parity(
    scenario: OnlyTestGenericT0Scenario,
) -> OnlyTestGenericT0ParityResult:
    legacy = _environment(scenario)
    planner = _environment(scenario)
    _prepare_environment(legacy, scenario)
    _prepare_environment(planner, scenario)
    legacy_update = _trade_update(legacy, scenario)
    planner_update = _trade_update(planner, scenario)
    assert legacy_update == planner_update
    context = only_test_real_trade_planning_context(planner, planner_update)
    manager_before = only_test_runtime_authority_digest(legacy)
    planner_before = only_test_runtime_authority_digest(planner)
    prepared = OnlyTradeExecutionTransactionPlanner().prepare(context)
    planner_after = only_test_runtime_authority_digest(planner)
    legacy_result = legacy.runtime.execution_processor.process(legacy_update)
    manager_after = only_test_runtime_authority_digest(legacy)
    return OnlyTestGenericT0ParityResult(
        scenario,
        context,
        prepared,
        legacy_result,
        manager_before,
        manager_after,
        planner_before,
        planner_after,
        only_test_legacy_projection_states(legacy, context),
    )


def only_test_generic_t0_projection_environment(
    scenario: OnlyTestGenericT0Scenario,
) -> tuple[OnlyIntegrationEnvironment, OnlyTradeExecutionPlanningContext, OnlyPreparedRuntimeTransaction]:
    """Return untouched real Managers plus the transaction planned from their authority."""

    environment = _environment(scenario)
    _prepare_environment(environment, scenario)
    context = only_test_real_trade_planning_context(environment, _trade_update(environment, scenario))
    return environment, context, OnlyTradeExecutionTransactionPlanner().prepare(context)


def only_test_generic_t0_legacy_environment(
    scenario: OnlyTestGenericT0Scenario,
) -> tuple[OnlyIntegrationEnvironment, OnlyTradeExecutionPlanningContext]:
    """Return the same real Managers after the legacy ExecutionProcessor path."""

    environment = _environment(scenario)
    _prepare_environment(environment, scenario)
    update = _trade_update(environment, scenario)
    context = only_test_real_trade_planning_context(environment, update)
    result = environment.runtime.execution_processor.process(update)
    assert result.status.value == "APPLIED"
    return environment, context


def only_test_generic_t0_trade_update(
    environment: OnlyIntegrationEnvironment,
    scenario: OnlyTestGenericT0Scenario,
    *,
    suffix: str,
    fill_price: str = "10.00",
) -> OnlyBrokerTradeUpdate:
    return _trade_update(environment, scenario, suffix=suffix, fill_price=fill_price)


def only_test_generic_t0_long_close_update(
    environment: OnlyIntegrationEnvironment,
    order_id: OnlyOrderId,
    *,
    suffix: str,
    fill_quantity: str,
    fill_price: str,
) -> OnlyBrokerTradeUpdate:
    scenario = OnlyTestGenericT0Scenario(f"long-close-{suffix}", fill_price=fill_price)
    return _trade_update_for_order(
        environment,
        order_id,
        scenario,
        suffix=suffix,
        fill_price=fill_price,
        fill_quantity=fill_quantity,
    )


def only_test_generic_t0_long_close_context(
    *,
    open_quantity: str = "100",
    close_quantity: str = "100",
    fill_quantity: str | None = None,
    fill_price: str = "12.00",
) -> tuple[OnlyIntegrationEnvironment, OnlyTradeExecutionPlanningContext, OnlyPreparedRuntimeTransaction]:
    environment, context = _only_test_generic_t0_long_close_before(
        open_quantity=open_quantity,
        close_quantity=close_quantity,
        fill_quantity=fill_quantity,
        fill_price=fill_price,
    )
    return environment, context, OnlyTradeExecutionTransactionPlanner().prepare(context)


def _only_test_generic_t0_long_close_before(
    *,
    open_quantity: str,
    close_quantity: str,
    fill_quantity: str | None,
    fill_price: str,
) -> tuple[OnlyIntegrationEnvironment, OnlyTradeExecutionPlanningContext]:
    scenario = OnlyTestGenericT0Scenario("long-close", fill_price=fill_price)
    environment = _environment(scenario)
    environment.start()
    for minute in range(3):
        environment.process_bar(DAY_ONE, minute, "10.00")
    environment.submit_buy(request_id="long-close-open", quantity=open_quantity)
    result = environment.fill_buy()
    assert result.status.value == "APPLIED"
    environment.settle_next_day()
    sell = environment.submit_sell(request_id="long-close", quantity=close_quantity)
    assert sell.order_id is not None
    update = _trade_update_for_order(
        environment,
        sell.order_id,
        scenario,
        suffix="close",
        fill_price=fill_price,
        fill_quantity=fill_quantity,
    )
    context = only_test_real_trade_planning_context(environment, update)
    return environment, context


def only_test_multi_cluster_close_context(
    *,
    close_quantity: str = "1000",
    fill_quantity: str | None = None,
    fill_price: str = "13.00",
) -> tuple[OnlyIntegrationEnvironment, OnlyTradeExecutionPlanningContext, OnlyPreparedRuntimeTransaction]:
    """Model A@10 plus B@12 while the order belongs to Allocation A."""

    environment, context = _only_test_generic_t0_long_close_before(
        open_quantity="1000",
        close_quantity=close_quantity,
        fill_quantity=fill_quantity,
        fill_price=fill_price,
    )
    assert context.position_before is not None
    assert context.allocation_before is not None
    position_before = replace(
        context.position_before,
        total_quantity=OnlyQuantity(Decimal("2000"), context.position_before.total_quantity.precision),
        settled_quantity=OnlyQuantity(Decimal("2000"), context.position_before.settled_quantity.precision),
        average_open_price=OnlyPrice(Decimal("11.00"), 2),
        cumulative_open_price_quantity=Decimal("22000.00"),
    )
    assert context.risk_reservation_before.reserved_notional is not None
    assert context.risk_reservation_before.consumed_notional is not None
    risk_currency = context.risk_reservation_before.reserved_notional.currency
    reserved_notional = OnlyMoney(
        (Decimal(fill_price) * Decimal(close_quantity)).quantize(Decimal("0.01")),
        risk_currency,
    )
    zero_notional = OnlyMoney(Decimal("0.00"), risk_currency)
    risk_reservation_before = replace(
        context.risk_reservation_before,
        reserved_notional=reserved_notional,
        consumed_notional=zero_notional,
        remaining_notional=reserved_notional,
        released_notional=zero_notional,
    )
    context = replace(
        context,
        position_before=position_before,
        risk_reservation_before=risk_reservation_before,
        aggregate_allocation_quantity_before=Decimal("2000"),
        aggregate_allocation_cumulative_cost_before=Decimal("22000.00"),
    )
    return environment, context, OnlyTradeExecutionTransactionPlanner().prepare(context)


def only_test_real_trade_planning_context(
    env: OnlyIntegrationEnvironment,
    update: OnlyBrokerTradeUpdate,
) -> OnlyTradeExecutionPlanningContext:
    runtime = env.runtime
    processor = runtime.execution_processor
    order = runtime.order_manager.require_snapshot(update.order_id)
    market_rules = processor._market_rules
    assert market_rules is not None
    trading_day = env.calendar.trading_day_at(update.ts_event)
    fallback = processor._position_scope_resolver.resolve_order(order)
    instruction = market_rules.build_trade_instruction(
        OnlyTradeApplicationRequest(
            str(order.instrument_id),
            str(order.order_id),
            str(update.fill.trade_id),
            str(order.account_id),
            order.side,
            update.fill.quantity.value,
            update.fill.price.value,
            update.ts_event.to_datetime(),
            trading_day,
            fallback.position_effect,
        )
    )
    compiled = market_rules.compiled_rules(str(order.instrument_id), trading_day)
    position_mode = (
        OnlyPositionMode.HEDGING
        if compiled.position_policy.mode is OnlyMarketPositionMode.HEDGING
        else OnlyPositionMode.NETTING
    )
    scope = processor._position_scope_resolver.resolve_trade(order, instruction, position_mode)
    fee_instruction = processor._resolve_fee_instruction(update, order, scope)
    position_before_snapshot = runtime.position_manager.get_snapshot(scope.position_key)
    allocation_before_snapshot = (
        None if scope.allocation_key is None else runtime.allocation_manager.get_snapshot(scope.allocation_key)
    )
    scoped_allocations = tuple(
        item
        for item in runtime.allocation_manager.list_by_instrument(order.instrument_id)
        if item.key.runtime_id == order.runtime_id
        and item.key.account_id == order.account_id
        and item.key.position_side is scope.position_side
    )
    account_snapshot = runtime.account_manager.get_snapshot(order.account_id)
    assert account_snapshot is not None
    account_reservation = next(
        (item for item in account_snapshot.reservations if item.order_id == order.order_id),
        None,
    )
    ledger_snapshot = runtime.strategy_ledger_locator.require_snapshot(
        runtime_id=order.runtime_id,
        account_id=order.account_id,
        cluster_id=order.cluster_id,
        currency=account_snapshot.base_currency,
    )
    strategy_reservation = next(
        (item for item in ledger_snapshot.reservations if item.order_id == order.order_id),
        None,
    )
    position_reservation = runtime.position_reservation_manager.get(order.order_id)
    risk_reservation = runtime.risk_service.reservations.get_for_order(order.order_id)
    assert risk_reservation is not None
    position_creation = None
    if position_before_snapshot is None:
        position_cycle = runtime.position_manager._cycles.get(scope.position_key, 0) + 1
        position_creation = OnlyPositionCreationAuthority(
            OnlyPositionId(
                f"POS-{scope.position_key.runtime_id}-{scope.position_key.account_id}-"
                f"{scope.position_key.instrument_id}-{scope.position_key.position_side.value}-{position_cycle:08d}"
            ),
            position_cycle,
        )
    allocation_creation = None
    if allocation_before_snapshot is None:
        assert scope.allocation_key is not None
        allocation_cycle = runtime.allocation_manager._cycles.get(scope.allocation_key, 0) + 1
        allocation_creation = OnlyAllocationCreationAuthority(
            OnlyPositionAllocationId(
                f"ALLOC-{scope.allocation_key.runtime_id}-{scope.allocation_key.account_id}-"
                f"{scope.allocation_key.cluster_id}-{scope.allocation_key.instrument_id}-{allocation_cycle:08d}"
            ),
            allocation_cycle,
        )
    valuation_time = account_snapshot.valuation_time or account_snapshot.updated_at
    account_timeline = runtime.account_performance_projector.timeline(order.account_id)
    ledger_timeline = runtime.strategy_ledger_manager.equity_timeline(ledger_snapshot.key)
    latest_mark = runtime._services.market_data_cache.latest_closed(env.bar_1m)
    assert latest_mark is not None
    return OnlyTradeExecutionPlanningContext(
        update=update,
        prepared_at=update.ts_init,
        engine_id=OnlyEngineId("integration-engine"),
        strategy_id=env.cluster.integration_strategy.strategy_id,
        processing_sequence=processor._processing_sequence + 1,
        trading_day=trading_day,
        contract_multiplier=env.instrument.contract_multiplier,
        valuation_price=latest_mark.close,
        position_scope=scope,
        trade_instruction=instruction,
        fee_instruction=fee_instruction,
        order_before=only_order_execution_state(order),
        position_before=(
            None if position_before_snapshot is None else only_position_execution_state(position_before_snapshot)
        ),
        allocation_before=(
            None if allocation_before_snapshot is None else only_allocation_execution_state(allocation_before_snapshot)
        ),
        aggregate_allocation_quantity_before=sum(
            (item.total_quantity.value for item in scoped_allocations), Decimal(0)
        ),
        aggregate_allocation_cumulative_cost_before=sum(
            (item.cumulative_open_price_quantity for item in scoped_allocations), Decimal(0)
        ),
        account_ledger_parity=(
            account_snapshot.cash.ledger_cash == ledger_snapshot.cash.ledger_cash
            and account_snapshot.position_market_value == ledger_snapshot.equity.position_market_value
        ),
        settlement_before=None,
        fee_before=None,
        order_fee_accrual_before=runtime.order_fee_accrual_manager.get(order.order_id),
        account_before=only_account_execution_state(account_snapshot),
        strategy_ledger_before=only_strategy_ledger_execution_state(ledger_snapshot),
        account_cash_reservation_before=(
            None if account_reservation is None else only_account_cash_reservation_execution_state(account_reservation)
        ),
        strategy_cash_reservation_before=(
            None
            if strategy_reservation is None
            else only_strategy_cash_reservation_execution_state(strategy_reservation)
        ),
        position_reservation_before=(
            None if position_reservation is None else only_position_reservation_execution_state(position_reservation)
        ),
        risk_reservation_before=only_risk_reservation_execution_state(risk_reservation),
        risk_before=only_risk_execution_state(runtime.risk_service.get_snapshot(order.cluster_id)),
        valuation_before=OnlyValuationExecutionState(
            order.account_id,
            valuation_time,
            account_snapshot.cash.ledger_cash,
            account_snapshot.position_market_value,
            account_snapshot.unrealized_pnl,
            account_snapshot.equity,
            runtime._account_valuation_version,
        ),
        fill_authority=only_capture_execution_fill_authority(runtime.execution_transaction_query, update),
        position_creation=position_creation,
        allocation_creation=allocation_creation,
        position_cycle=runtime.position_manager._cycles.get(scope.position_key, 0),
        allocation_cycle=(
            0 if scope.allocation_key is None else runtime.allocation_manager._cycles.get(scope.allocation_key, 0)
        ),
        settlement_record_sequence=runtime.settlement_authority.sequence_head,
        fee_record_sequence=runtime.fee_manager.sequence_head,
        account_equity_sequence=0 if not account_timeline else account_timeline[-1].sequence,
        ledger_equity_sequence=runtime.strategy_ledger_manager.equity_sequence_head,
        account_external_cash_flow=(
            OnlyMoney(Decimal(0), account_snapshot.base_currency)
            if not account_timeline
            else account_timeline[-1].external_cash_flow
        ),
        ledger_equity_before=None if not ledger_timeline else ledger_timeline[-1],
        ledger_high_water_mark=ledger_snapshot.equity.high_water_mark,
    )


def only_test_legacy_projection_states(
    env: OnlyIntegrationEnvironment,
    context: OnlyTradeExecutionPlanningContext,
) -> tuple[tuple[OnlyRuntimeProjectionComponent, object], ...]:
    runtime = env.runtime
    order = runtime.order_manager.require_snapshot(context.update.order_id)
    position = runtime.position_manager.require_snapshot(context.position_scope.position_key)
    assert context.position_scope.allocation_key is not None
    allocation = runtime.allocation_manager.get_snapshot(context.position_scope.allocation_key)
    assert allocation is not None
    account = runtime.account_manager.get_snapshot(order.account_id)
    assert account is not None
    ledger = runtime.strategy_ledger_locator.require_snapshot(
        runtime_id=order.runtime_id,
        account_id=order.account_id,
        cluster_id=order.cluster_id,
        currency=account.base_currency,
    )
    account_reservation = next(item for item in account.reservations if item.order_id == order.order_id)
    strategy_reservation = next(item for item in ledger.reservations if item.order_id == order.order_id)
    risk_reservation = runtime.risk_service.reservations.get_for_order(order.order_id)
    assert risk_reservation is not None
    settlement_authority = next(
        item
        for item in runtime.settlement_authority.snapshots()
        if item.instruction.trade_id == context.update.fill.trade_id
    )
    settlement = only_settlement_execution_state(settlement_authority)
    fee_records = tuple(
        OnlyFeeRecordReplay(
            item.fee_record_id,
            item.instruction_id,
            item.account_id,
            item.order_id,
            item.trade_id,
            OnlyMoney(item.charged, account.base_currency),
            item.fee_type,
        )
        for item in runtime.fee_manager.records
        if item.instruction_id == context.fee_instruction.instruction_id
    )
    fee_state = OnlyFeeExecutionState(
        OnlyFeeInstructionReplay(
            context.fee_instruction.instruction_id,
            context.fee_instruction.runtime_id,
            context.fee_instruction.cluster_id,
            context.fee_instruction.account_id,
            context.fee_instruction.order_id,
            context.fee_instruction.trade_id,
            context.fee_instruction.calculation_source,
            context.fee_instruction.idempotency_key,
            OnlyTimestamp.from_datetime(context.fee_instruction.created_at),
        ),
        fee_records,
        context.fee_instruction.fee_breakdown.total,
        context.fee_instruction.fee_breakdown,
        1,
        runtime.fee_manager.sequence_head,
    )
    valuation_time = account.valuation_time or account.updated_at
    return (
        (OnlyRuntimeProjectionComponent.ORDER, only_order_execution_state(order)),
        (OnlyRuntimeProjectionComponent.POSITION, only_position_execution_state(position)),
        (OnlyRuntimeProjectionComponent.ALLOCATION, only_allocation_execution_state(allocation)),
        (OnlyRuntimeProjectionComponent.SETTLEMENT, settlement),
        (
            OnlyRuntimeProjectionComponent.ORDER_FEE_ACCRUAL,
            runtime.order_fee_accrual_manager.get(order.order_id),
        ),
        (OnlyRuntimeProjectionComponent.FEE, fee_state),
        (OnlyRuntimeProjectionComponent.ACCOUNT, only_account_execution_state(account)),
        (OnlyRuntimeProjectionComponent.STRATEGY_LEDGER, only_strategy_ledger_execution_state(ledger)),
        (
            OnlyRuntimeProjectionComponent.ACCOUNT_CASH_RESERVATION,
            only_account_cash_reservation_execution_state(account_reservation),
        ),
        (
            OnlyRuntimeProjectionComponent.STRATEGY_CASH_RESERVATION,
            only_strategy_cash_reservation_execution_state(strategy_reservation),
        ),
        (
            OnlyRuntimeProjectionComponent.RISK_RESERVATION,
            only_risk_reservation_execution_state(risk_reservation),
        ),
        (
            OnlyRuntimeProjectionComponent.RISK,
            only_risk_execution_state(runtime.risk_service.get_snapshot(order.cluster_id)),
        ),
        (
            OnlyRuntimeProjectionComponent.VALUATION,
            OnlyValuationExecutionState(
                order.account_id,
                valuation_time,
                account.cash.ledger_cash,
                account.position_market_value,
                account.unrealized_pnl,
                account.equity,
                runtime._account_valuation_version,
            ),
        ),
    )


def only_test_projection_after(projection: OnlyRuntimeProjection) -> object:
    return projection.after


def _environment(scenario: OnlyTestGenericT0Scenario) -> OnlyIntegrationEnvironment:
    fee_config = OnlyFeeResolverConfig(
        market_mode=(OnlyFeeConfigurationMode.DEFAULT if scenario.fee_enabled else OnlyFeeConfigurationMode.NONE)
    )
    return OnlyIntegrationEnvironment(
        market_profile_id=OnlyMarketProfileId.GENERIC_T0_CASH,
        fee_resolver_config=fee_config,
        virtual_broker=scenario.virtual_broker,
    )


def _prepare_environment(env: OnlyIntegrationEnvironment, scenario: OnlyTestGenericT0Scenario) -> None:
    env.start()
    for minute in range(3):
        env.process_bar(DAY_ONE, minute, "10.00")
    if scenario.existing_position:
        env.submit_buy(request_id="parity-seed")
        result = env.fill_buy()
        assert result.status.value == "APPLIED"
        env.submit_buy(request_id="parity-second", price="12.00", minute=5)
    else:
        env.submit_buy(request_id=f"parity-{scenario.name}")


def _trade_update(
    env: OnlyIntegrationEnvironment,
    scenario: OnlyTestGenericT0Scenario,
    *,
    suffix: str | None = None,
    fill_price: str | None = None,
) -> OnlyBrokerTradeUpdate:
    assert env.buy_order is not None and env.buy_order.order_id is not None
    return _trade_update_for_order(
        env,
        env.buy_order.order_id,
        scenario,
        suffix=suffix,
        fill_price=fill_price,
    )


def _trade_update_for_order(
    env: OnlyIntegrationEnvironment,
    order_id: OnlyOrderId,
    scenario: OnlyTestGenericT0Scenario,
    *,
    suffix: str | None = None,
    fill_price: str | None = None,
    fill_quantity: str | None = None,
) -> OnlyBrokerTradeUpdate:
    order = env.runtime.order_manager.require_snapshot(order_id)
    timestamp = OnlyTimestamp.from_unix_nanos(env.runtime.clock.timestamp_ns())
    env.runtime.clock.advance_by(7_000_000_000)
    initialized_at = OnlyTimestamp.from_unix_nanos(env.runtime.clock.timestamp_ns())
    name = scenario.name if suffix is None else f"{scenario.name}-{suffix}"
    price = fill_price or scenario.fill_price
    source_sequence = (order.last_external_sequence or 0) + 1
    update_id = OnlyBrokerUpdateId(f"parity-update-{name}")
    fill = OnlyOrderFill(
        OnlyTradeId(f"parity-trade-{name}"),
        order.order_id,
        OnlyPrice(Decimal(price), 2),
        (order.quantity if fill_quantity is None else OnlyQuantity(Decimal(fill_quantity), order.quantity.precision)),
        timestamp,
        initialized_at,
        OnlyVenueTradeId(f"parity-venue-trade-{name}"),
        order.venue_order_id,
        liquidity_side=OnlyLiquiditySide.TAKER,
        external_sequence=source_sequence,
        external_event_id=str(update_id),
    )
    return OnlyBrokerTradeUpdate(
        runtime_id=order.runtime_id,
        gateway_id=OnlyBrokerGatewayId("virtual-integration"),
        account_id=order.account_id,
        update_id=update_id,
        source_sequence=source_sequence,
        ts_event=timestamp,
        ts_init=initialized_at,
        correlation_id=str(order.order_id),
        causation_id="generic-t0-manager-parity",
        order_id=order.order_id,
        fill=fill,
    )


__all__ = [name for name in globals() if name.startswith("OnlyTest") or name.startswith("only_test_")]
